from __future__ import annotations

import pytest

from scripts.calibrate_camera_rois import build_roi_config


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
