"""Poll a camera JPEG endpoint and forward frames to the existing occupancy API."""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image, UnidentifiedImageError

LOGGER = logging.getLogger("smart_parking.camera_ingest")
DEFAULT_CAMERA_URL = "http://esp32-cam.local/capture"
DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"
MAX_TIMEOUT_SECONDS = 60.0
MAX_CAPTURE_INTERVAL_SECONDS = 300.0
MAX_BACKOFF_SECONDS = 300.0
BACKEND_IMAGE_LIMIT_BYTES = 5 * 1024 * 1024


class CameraIngestError(RuntimeError):
    """A camera frame could not be safely validated or forwarded."""


@dataclass(frozen=True)
class CameraIngestConfig:
    camera_url: str
    backend_url: str
    interval_seconds: float = 5.0
    timeout_seconds: float = 5.0
    maximum_frame_bytes: int = 5 * 1024 * 1024
    maximum_backoff_seconds: float = 60.0

    def __post_init__(self) -> None:
        if not self.camera_url.startswith(("http://", "https://")):
            raise ValueError("camera URL must use HTTP or HTTPS")
        if not self.backend_url.startswith(("http://", "https://")):
            raise ValueError("backend URL must use HTTP or HTTPS")
        if self.interval_seconds < 2.0:
            raise ValueError("capture interval must be at least 2 seconds")
        if self.interval_seconds > MAX_CAPTURE_INTERVAL_SECONDS:
            raise ValueError("capture interval must be bounded to 300 seconds")
        if self.timeout_seconds <= 0 or self.timeout_seconds > MAX_TIMEOUT_SECONDS:
            raise ValueError("request timeout must be positive and bounded to 60 seconds")
        if self.maximum_frame_bytes <= 0:
            raise ValueError("maximum frame size must be positive")
        if self.maximum_frame_bytes > BACKEND_IMAGE_LIMIT_BYTES:
            raise ValueError("maximum frame size must not exceed the backend 5 MiB size limit")
        if (
            self.maximum_backoff_seconds < self.interval_seconds
            or self.maximum_backoff_seconds > MAX_BACKOFF_SECONDS
        ):
            raise ValueError("maximum backoff must cover the interval and stay within 300 seconds")


class CameraIngestor:
    """Synchronous, bounded poller with one in-flight frame at a time."""

    def __init__(
        self,
        config: CameraIngestConfig,
        *,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self.config = config
        self._opener = opener

    def capture_once(self) -> dict[str, Any]:
        try:
            frame = self._capture()
            self._validate_jpeg(frame)
            payload = self._multipart(frame)
            response = self._opener(
                Request(
                    f"{self.config.backend_url.rstrip('/')}/api/camera/occupancy",
                    data=payload,
                    headers={
                        "Accept": "application/json",
                        "Content-Type": f"multipart/form-data; boundary={self._boundary}",
                    },
                    method="POST",
                ),
                timeout=self.config.timeout_seconds,
            )
            with response:
                response_bytes = response.read(1024 * 1024 + 1)
            if len(response_bytes) > 1024 * 1024:
                raise CameraIngestError("backend response exceeds 1 MiB")
            result = json.loads(response_bytes)
            if not isinstance(result, dict) or not isinstance(result.get("slots"), list):
                raise CameraIngestError("backend returned an invalid occupancy response")
            return result
        except CameraIngestError:
            raise
        except (
            HTTPError,
            URLError,
            TimeoutError,
            OSError,
            ValueError,
            UnidentifiedImageError,
        ) as exc:
            raise CameraIngestError("camera frame request or backend upload failed") from exc

    @property
    def _boundary(self) -> str:
        return self.__boundary

    def _capture(self) -> bytes:
        try:
            with self._opener(
                Request(self.config.camera_url, headers={"Accept": "image/jpeg"}),
                timeout=self.config.timeout_seconds,
            ) as response:
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
                if content_type != "image/jpeg":
                    raise CameraIngestError("camera endpoint did not return image/jpeg")
                frame = response.read(self.config.maximum_frame_bytes + 1)
        except CameraIngestError:
            raise
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise CameraIngestError("camera snapshot request failed") from exc
        if not frame:
            raise CameraIngestError("camera returned an empty frame")
        if len(frame) > self.config.maximum_frame_bytes:
            raise CameraIngestError("camera frame exceeds configured size limit")
        return frame

    @staticmethod
    def _validate_jpeg(frame: bytes) -> None:
        try:
            with Image.open(BytesIO(frame)) as image:
                if image.format != "JPEG":
                    raise CameraIngestError("camera frame must be a valid JPEG")
                image.verify()
        except (Image.DecompressionBombError, OSError, SyntaxError, UnidentifiedImageError) as exc:
            raise CameraIngestError("camera frame must be a valid JPEG") from exc

    def _multipart(self, frame: bytes) -> bytes:
        self.__boundary = f"smart-parking-{uuid.uuid4().hex}"
        boundary = self._boundary.encode("ascii")
        return b"\r\n".join(
            (
                b"--" + boundary,
                b'Content-Disposition: form-data; name="image"; filename="capture.jpg"',
                b"Content-Type: image/jpeg",
                b"",
                frame,
                b"--" + boundary + b"--",
                b"",
            )
        )

    def run(self, stop_event: Any) -> None:
        backoff = self.config.interval_seconds
        while not stop_event.is_set():
            started = time.monotonic()
            try:
                result = self.capture_once()
                LOGGER.info("occupancy frame accepted for %d slots", len(result["slots"]))
                backoff = self.config.interval_seconds
                delay = max(0.0, self.config.interval_seconds - (time.monotonic() - started))
            except CameraIngestError:
                LOGGER.warning("camera ingestion failed; retrying with bounded backoff")
                delay = backoff
                backoff = min(backoff * 2, self.config.maximum_backoff_seconds)
            stop_event.wait(delay)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--camera-url", default=os.getenv("SMART_PARKING_CAMERA_URL", DEFAULT_CAMERA_URL)
    )
    parser.add_argument(
        "--backend-url", default=os.getenv("SMART_PARKING_BACKEND_URL", DEFAULT_BACKEND_URL)
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=float(os.getenv("SMART_PARKING_CAMERA_INTERVAL_SECONDS", "5")),
    )
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    parser.add_argument("--maximum-frame-bytes", type=int, default=5 * 1024 * 1024)
    parser.add_argument("--once", action="store_true", help="capture and post one frame, then exit")
    args = parser.parse_args(argv)
    try:
        ingestor = CameraIngestor(
            CameraIngestConfig(
                camera_url=args.camera_url,
                backend_url=args.backend_url,
                interval_seconds=args.interval_seconds,
                timeout_seconds=args.timeout_seconds,
                maximum_frame_bytes=args.maximum_frame_bytes,
                maximum_backoff_seconds=min(MAX_BACKOFF_SECONDS, max(60.0, args.interval_seconds)),
            )
        )
        if args.once:
            response = ingestor.capture_once()
            print(
                json.dumps(
                    {"detector": response.get("detector"), "slot_count": len(response["slots"])}
                )
            )
            return 0
    except (ValueError, CameraIngestError) as exc:
        LOGGER.error("camera ingestion setup or one-shot capture failed: %s", exc)
        return 2

    import threading

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    stop_event = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda _signum, _frame: stop_event.set())
    ingestor.run(stop_event)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
