"""Drive the hardware-independent camera, lifecycle, allocation, and prediction demo."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from io import BytesIO
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image

DEFAULT_WEIGHTS = {"distance": 0.35, "congestion": 0.30, "waiting": 0.20, "fairness": 0.15}
DEMO_SEED = 20260912
DEMO_SCENARIO_ID = "simulated-demo"


class DemoRequestError(RuntimeError):
    """Raised when the running Smart Parking API cannot complete a demo request."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--rfid-uid", default="DEMO-CARD-001")
    parser.add_argument("--idempotency-key", default="simulated-demo-entry-001")
    parser.add_argument("--camera-frames", type=int, default=3)
    return parser


def request_json(
    base_url: str, path: str, *, payload: object | None = None
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(f"{base_url.rstrip('/')}{path}", data=data)
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urlopen(request, timeout=10) as response:
            loaded = json.load(response)
    except (HTTPError, URLError, TimeoutError) as error:
        raise DemoRequestError("demo request failed") from error
    if not isinstance(loaded, dict):
        raise DemoRequestError("demo API response must be a JSON object")
    return loaded


def _synthetic_jpeg() -> bytes:
    image = Image.new("RGB", (1280, 720), color="white")
    buffer = BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def post_camera_frame(base_url: str, image: bytes) -> dict[str, Any]:
    boundary = "----smart-parking-demo-boundary"
    body = b"".join(
        (
            f"--{boundary}\r\n".encode("ascii"),
            b'Content-Disposition: form-data; name="image"; filename="demo.jpg"\r\n',
            b"Content-Type: image/jpeg\r\n\r\n",
            image,
            f"\r\n--{boundary}--\r\n".encode("ascii"),
        )
    )
    request = Request(f"{base_url.rstrip('/')}/api/camera/occupancy", data=body)
    request.add_header("Accept", "application/json")
    request.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        with urlopen(request, timeout=10) as response:
            loaded = json.load(response)
    except (HTTPError, URLError, TimeoutError) as error:
        raise DemoRequestError("camera demo request failed") from error
    if not isinstance(loaded, dict):
        raise DemoRequestError("camera API response must be a JSON object")
    return loaded


def allocation_payload(status: dict[str, Any]) -> dict[str, Any]:
    slots = status.get("slots")
    if not isinstance(slots, list) or not slots:
        raise DemoRequestError("parking status has no slots")
    zone_totals = Counter(str(slot["zone"]) for slot in slots)
    zone_occupied = Counter(str(slot["zone"]) for slot in slots if slot["occupied"])
    candidates = [
        {
            "slot_id": slot["id"],
            "occupied": slot["occupied"],
            "distance": slot["walking_distance"],
            "congestion": zone_occupied[str(slot["zone"])] / zone_totals[str(slot["zone"])],
            "waiting": 0.0,
            "fairness": 0.0,
        }
        for slot in slots
    ]
    return {
        "algorithm": "all",
        "request": {
            "scenario_id": DEMO_SCENARIO_ID,
            "candidates": candidates,
            "weights": DEFAULT_WEIGHTS,
            "seed": DEMO_SEED,
            "iterations": 30,
        },
    }


def run_demo(
    base_url: str, rfid_uid: str, idempotency_key: str, camera_frames: int
) -> dict[str, Any]:
    if camera_frames < 1:
        raise DemoRequestError("camera frames must be positive")
    camera = [post_camera_frame(base_url, _synthetic_jpeg()) for _ in range(camera_frames)]
    entry = request_json(
        base_url,
        "/api/vehicle/entry",
        payload={"rfid_uid": rfid_uid, "idempotency_key": idempotency_key},
    )
    status_before = request_json(base_url, "/api/parking/status")
    benchmarks = request_json(
        base_url, "/api/allocation/run", payload=allocation_payload(status_before)
    )
    prediction = request_json(base_url, "/api/prediction")
    status_after = request_json(base_url, "/api/parking/status")
    slots = status_after.get("slots", [])
    if not isinstance(slots, list):
        raise DemoRequestError("parking status slots must be a list")
    results = benchmarks.get("results", [])
    if not isinstance(results, list):
        raise DemoRequestError("allocation results must be a list")
    return {
        "camera_frames": len(camera),
        "entry_slot": entry["slot_name"],
        "optimizer_results": [
            {
                "algorithm": result["algorithm"],
                "chosen_slot_id": result["chosen_slot_id"],
                "best_cost": result["best_cost"],
                "runtime_ms": result["runtime_ms"],
            }
            for result in results
        ],
        "forecast": {
            "model": prediction["model"],
            "occupancy_ratio": prediction["occupancy_ratio"],
            "target_at": prediction["target_at"],
            "fallback_reason": prediction["fallback_reason"],
        },
        "occupancy": {
            "occupied": sum(bool(slot["occupied"]) for slot in slots),
            "total": len(slots),
        },
    }


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        summary = run_demo(
            arguments.base_url,
            arguments.rfid_uid,
            arguments.idempotency_key,
            arguments.camera_frames,
        )
    except DemoRequestError as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
