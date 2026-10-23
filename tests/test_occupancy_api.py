from __future__ import annotations

import json
import sqlite3
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from backend.app.config import Settings
from backend.app.main import create_app


def write_settings_files(
    tmp_path: Path,
    *,
    slot_ids: tuple[int, ...] = (2, 9, 21),
    roi_widths: tuple[int, ...] | None = None,
    max_image_bytes: int = 1024 * 1024,
) -> Settings:
    tmp_path.mkdir(parents=True, exist_ok=True)
    parking_path = tmp_path / "parking.yaml"
    roi_path = tmp_path / "rois.json"
    parking_path.write_text(
        "slots:\n"
        + "\n".join(
            f"  - {{id: {slot_id}, name: S{slot_id}, walking_distance: 0.5, zone: test}}"
            for slot_id in slot_ids
        )
        + "\n",
        encoding="utf-8",
    )
    widths = roi_widths or tuple(10 for _ in slot_ids)
    roi_path.write_text(
        json.dumps(
            {
                "heuristic": {
                    "edge_threshold": 0.25,
                    "minimum_confidence": 0.30,
                    "required_consecutive_frames": 3,
                },
                "slots": [
                    {
                        "slot_id": slot_id,
                        "x": index * 10,
                        "y": 0,
                        "width": width,
                        "height": 10,
                    }
                    for index, (slot_id, width) in enumerate(
                        zip(slot_ids, widths, strict=True)
                    )
                ],
            }
        ),
        encoding="utf-8",
    )
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'parking.db'}",
        parking_config_path=parking_path,
        roi_config_path=roi_path,
        camera_max_image_bytes=max_image_bytes,
    )


def image_bytes(image_format: str = "JPEG") -> bytes:
    image = Image.new("L", (30, 10))
    for y in range(image.height):
        for x in range(image.width):
            image.putpixel((x, y), 255 if (x + y) % 2 else 0)
    stream = BytesIO()
    image.save(stream, format=image_format, quality=100, subsampling=0)
    return stream.getvalue()


def post_image(client: TestClient, payload: bytes, filename: str = "frame.jpg"):
    return client.post(
        "/api/camera/occupancy",
        files={"image": (filename, payload, "image/jpeg")},
    )


def test_camera_api_processes_all_dynamic_slots_and_persists_smoothed_state(
    tmp_path: Path,
) -> None:
    settings = write_settings_files(tmp_path)
    payload = image_bytes()

    with TestClient(create_app(settings)) as client:
        first = post_image(client, payload)
        second = post_image(client, payload)
        third = post_image(client, payload)
        status = client.get("/api/parking/status")

    assert first.status_code == second.status_code == third.status_code == 200
    assert [slot["slot_id"] for slot in first.json()["slots"]] == [2, 9, 21]
    assert [slot["outcome"] for slot in first.json()["slots"]] == ["pending"] * 3
    assert [slot["consecutive_frames"] for slot in second.json()["slots"]] == [2] * 3
    assert [slot["outcome"] for slot in third.json()["slots"]] == ["accepted"] * 3
    assert [slot["accepted_occupied"] for slot in third.json()["slots"]] == [True] * 3
    assert [slot["id"] for slot in status.json()["slots"]] == [2, 9, 21]
    assert [slot["occupied"] for slot in status.json()["slots"]] == [True] * 3
    with sqlite3.connect(settings.database_path) as connection:
        events = connection.execute(
            "SELECT slot_id, occupied, source FROM occupancy_events ORDER BY slot_id"
        ).fetchall()
    assert events == [
        (2, 1, "camera_heuristic"),
        (9, 1, "camera_heuristic"),
        (21, 1, "camera_heuristic"),
    ]


def test_camera_api_input_error_does_not_change_persistence_or_smoothing(
    tmp_path: Path,
) -> None:
    settings = write_settings_files(tmp_path)
    jpeg = image_bytes()

    with TestClient(create_app(settings)) as client:
        first = post_image(client, jpeg)
        invalid = post_image(client, image_bytes("PNG"), "frame.png")
        second = post_image(client, jpeg)

    assert first.json()["slots"][0]["consecutive_frames"] == 1
    assert float(first.headers["X-Camera-Processing-Ms"]) >= 0
    assert "camera_process;dur=" in first.headers["Server-Timing"]
    assert invalid.status_code == 400
    assert invalid.json()["detail"]["code"] == "invalid_image"
    assert second.json()["slots"][0]["consecutive_frames"] == 2
    with sqlite3.connect(settings.database_path) as connection:
        occupied = connection.execute(
            "SELECT occupied FROM parking_slots ORDER BY id"
        ).fetchall()
        event_count = connection.execute("SELECT COUNT(*) FROM occupancy_events").fetchone()[0]
    assert occupied == [(0,), (0,), (0,)]
    assert event_count == 0


def test_camera_api_returns_structured_upload_errors(tmp_path: Path) -> None:
    normal_settings = write_settings_files(tmp_path / "normal")
    with TestClient(create_app(normal_settings)) as client:
        missing = client.post("/api/camera/occupancy")
        empty = post_image(client, b"")
    assert missing.status_code == 422
    assert empty.status_code == 400
    assert empty.json()["detail"]["code"] == "empty_image"

    small_settings = write_settings_files(tmp_path / "small", max_image_bytes=3)
    with TestClient(create_app(small_settings)) as client:
        oversized = post_image(client, b"1234")
    assert oversized.status_code == 413
    assert oversized.json()["detail"]["code"] == "image_too_large"

    bounds_settings = write_settings_files(
        tmp_path / "bounds", roi_widths=(10, 10, 11)
    )
    with TestClient(create_app(bounds_settings)) as client:
        out_of_bounds = post_image(client, image_bytes())
    assert out_of_bounds.status_code == 400
    assert out_of_bounds.json()["detail"]["code"] == "roi_out_of_bounds"
