from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from urllib.error import URLError

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.app.main import create_app
from scripts.camera_ingest import CameraIngestConfig, CameraIngestError, CameraIngestor
from tests.test_occupancy_api import image_bytes, write_settings_files


def jpeg_fixture() -> bytes:
    stream = BytesIO()
    Image.new("RGB", (32, 24), (30, 80, 120)).save(stream, format="JPEG")
    return stream.getvalue()


class CameraBackend:
    def __init__(self, frame: bytes | None = None) -> None:
        self.frame = frame if frame is not None else jpeg_fixture()
        self.uploads: list[bytes] = []
        self.backend_authorization: list[str | None] = []
        self.camera_authorization: list[str | None] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                owner.camera_authorization.append(self.headers.get("Authorization"))
                if self.path != "/capture":
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(owner.frame)))
                self.end_headers()
                self.wfile.write(owner.frame)

            def do_POST(self) -> None:
                owner.backend_authorization.append(self.headers.get("Authorization"))
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                owner.uploads.append(body)
                payload = json.dumps(
                    {"detector": "heuristic", "slots": [{"slot_id": 1, "outcome": "unchanged"}]}
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("X-Camera-Processing-Ms", "2.75")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_args: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


def test_camera_ingestor_validates_jpeg_and_posts_to_existing_api(tmp_path) -> None:
    service = CameraBackend()
    metrics_path = tmp_path / "events.jsonl"
    try:
        result = CameraIngestor(
            CameraIngestConfig(
                camera_url=f"{service.base_url}/capture",
                backend_url=service.base_url,
                interval_seconds=2.0,
            ),
            metrics_jsonl=metrics_path,
        ).capture_once()
    finally:
        service.close()

    assert result["detector"] == "heuristic"
    assert len(service.uploads) == 1
    assert b'name="image"' in service.uploads[0]
    assert b"Content-Type: image/jpeg" in service.uploads[0]
    assert jpeg_fixture() in service.uploads[0]
    event = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert event["event"] == "camera_processing"
    assert event["latency_ms"] == 2.75
    assert event["success"] is True


def test_camera_ingestor_does_not_forward_invalid_jpeg() -> None:
    service = CameraBackend(frame=b"not a JPEG")
    try:
        ingestor = CameraIngestor(
            CameraIngestConfig(
                camera_url=f"{service.base_url}/capture",
                backend_url=service.base_url,
                interval_seconds=2.0,
            )
        )
        with pytest.raises(CameraIngestError, match="valid JPEG"):
            ingestor.capture_once()
    finally:
        service.close()

    assert service.uploads == []


def test_camera_ingestor_sends_optional_backend_token_only_to_api() -> None:
    service = CameraBackend()
    try:
        CameraIngestor(
            CameraIngestConfig(
                camera_url=f"{service.base_url}/capture",
                backend_url=service.base_url,
                interval_seconds=2.0,
            ),
            api_token="private-test-token",
        ).capture_once()
    finally:
        service.close()

    assert service.camera_authorization == [None]
    assert service.backend_authorization == ["Bearer private-test-token"]


def test_camera_ingestor_reports_camera_offline_without_uploading() -> None:
    requests: list[str] = []

    def offline_opener(request, *, timeout):
        requests.append(request.full_url)
        raise URLError("camera offline")

    ingestor = CameraIngestor(
        CameraIngestConfig(
            camera_url="http://camera/capture",
            backend_url="http://backend",
            interval_seconds=2,
        ),
        opener=offline_opener,
    )

    with pytest.raises(CameraIngestError, match="snapshot request failed"):
        ingestor.capture_once()

    assert requests == ["http://camera/capture"]


def test_camera_ingestor_rejects_malformed_backend_response() -> None:
    class Response:
        def __init__(self, body: bytes, content_type: str) -> None:
            self.body = body
            self.headers = {"Content-Type": content_type}

        def read(self, _limit: int = -1) -> bytes:
            return self.body

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    calls = 0

    def malformed_backend_opener(_request, *, timeout):
        nonlocal calls
        assert timeout > 0
        calls += 1
        if calls == 1:
            return Response(jpeg_fixture(), "image/jpeg")
        return Response(b"{not-json", "application/json")

    ingestor = CameraIngestor(
        CameraIngestConfig(
            camera_url="http://camera/capture",
            backend_url="http://backend",
            interval_seconds=2,
        ),
        opener=malformed_backend_opener,
    )

    with pytest.raises(CameraIngestError, match="camera frame request or backend upload failed"):
        ingestor.capture_once()

    assert calls == 2


def test_camera_ingestor_rejects_invalid_intervals() -> None:
    with pytest.raises(ValueError, match="interval"):
        CameraIngestConfig(
            camera_url="http://camera/capture",
            backend_url="http://localhost:8000",
            interval_seconds=0.5,
        )


def test_camera_ingest_configuration_keeps_time_and_memory_limits_bounded() -> None:
    with pytest.raises(ValueError, match="bounded"):
        CameraIngestConfig(
            camera_url="http://camera/capture",
            backend_url="http://localhost:8000",
            interval_seconds=2,
            timeout_seconds=61,
        )
    with pytest.raises(ValueError, match="size limit"):
        CameraIngestConfig(
            camera_url="http://camera/capture",
            backend_url="http://localhost:8000",
            interval_seconds=2,
            maximum_frame_bytes=5 * 1024 * 1024 + 1,
        )


def test_camera_ingestion_reaches_real_occupancy_api(tmp_path) -> None:
    payload = image_bytes()
    settings = write_settings_files(tmp_path)

    class Response:
        def __init__(self, body: bytes, content_type: str) -> None:
            self.body = body
            self.headers = {"Content-Type": content_type}

        def read(self, _limit: int = -1) -> bytes:
            return self.body

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    with TestClient(create_app(settings)) as client:

        def opener(request, *, timeout):
            assert timeout > 0
            if request.full_url.endswith("/capture"):
                return Response(payload, "image/jpeg")
            response = client.post(
                "/api/camera/occupancy",
                content=request.data,
                headers={"content-type": request.headers["Content-type"]},
            )
            return Response(response.content, "application/json")

        result = CameraIngestor(
            CameraIngestConfig(
                camera_url="http://camera/capture",
                backend_url="http://backend",
                interval_seconds=2,
            ),
            opener=opener,
        ).capture_once()
        status = client.get("/api/parking/status")

    assert result["detector"] == "heuristic"
    assert len(result["slots"]) == 3
    assert status.status_code == 200
