from __future__ import annotations

import pytest

from scripts.calibrate_camera_rois import build_roi_config, capture_jpeg


def test_roi_calibration_accepts_in_bounds_regions_for_every_slot() -> None:
    result = build_roi_config(
        image_size=(800, 600),
        slot_ids=(1, 2),
        rectangles={1: (10, 20, 100, 90), 2: (120, 20, 100, 90)},
        heuristic={
            "edge_threshold": 0.12,
            "minimum_confidence": 0.7,
            "required_consecutive_frames": 3,
        },
    )

    assert result == {
        "heuristic": {
            "edge_threshold": 0.12,
            "minimum_confidence": 0.7,
            "required_consecutive_frames": 3,
        },
        "slots": [
            {"slot_id": 1, "x": 10, "y": 20, "width": 100, "height": 90},
            {"slot_id": 2, "x": 120, "y": 20, "width": 100, "height": 90},
        ],
    }


def test_roi_calibration_rejects_out_of_bounds_or_overlapping_regions() -> None:
    heuristic = {
        "edge_threshold": 0.12,
        "minimum_confidence": 0.7,
        "required_consecutive_frames": 3,
    }
    with pytest.raises(ValueError, match="outside image"):
        build_roi_config(
            image_size=(100, 100),
            slot_ids=(1,),
            rectangles={1: (90, 0, 20, 20)},
            heuristic=heuristic,
        )
    with pytest.raises(ValueError, match="overlap"):
        build_roi_config(
            image_size=(100, 100),
            slot_ids=(1, 2),
            rectangles={1: (0, 0, 50, 50), 2: (40, 40, 50, 50)},
            heuristic=heuristic,
        )


@pytest.mark.parametrize(
    ("timeout", "maximum_bytes"),
    [(0, 1024), (-1, 1024), (5, 0), (5, -1), (5, 5 * 1024 * 1024 + 1)],
)
def test_camera_capture_rejects_unbounded_or_invalid_limits(
    monkeypatch: pytest.MonkeyPatch, timeout: float, maximum_bytes: int
) -> None:
    called = False

    def unexpected_open(*_args: object, **_kwargs: object) -> None:
        nonlocal called
        called = True
        raise AssertionError("validation must happen before the network request")

    monkeypatch.setattr("scripts.calibrate_camera_rois.urlopen", unexpected_open)
    with pytest.raises(ValueError, match=r"timeout|size limit"):
        capture_jpeg(
            "http://camera/capture", timeout=timeout, maximum_bytes=maximum_bytes
        )

    assert called is False


def test_camera_capture_requires_jpeg_content_type(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        def __init__(self) -> None:
            self.headers = {"Content-Type": "text/plain"}

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr("scripts.calibrate_camera_rois.urlopen", lambda *_a, **_k: Response())
    with pytest.raises(ValueError, match="image/jpeg"):
        capture_jpeg("http://camera/capture")
