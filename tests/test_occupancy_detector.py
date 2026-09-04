from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from backend.app.config import Settings
from vision.detector import HeuristicDetector, VisionInputError
from vision.models import HeuristicConfig, RoiConfig, RoiRegion


def jpeg_bytes(image: Image.Image) -> bytes:
    stream = BytesIO()
    image.save(stream, format="JPEG", quality=100, subsampling=0)
    return stream.getvalue()


def detector_frame() -> Image.Image:
    image = Image.new("L", (20, 10), color=0)
    for y in range(10):
        for x in range(10, 20):
            image.putpixel((x, y), 255 if (x + y) % 2 else 0)
    return image


def detector_for_slots(
    slot_ids: list[int], max_image_bytes: int = 1024 * 1024
) -> HeuristicDetector:
    return HeuristicDetector(
        RoiConfig(
            heuristic=HeuristicConfig(
                edge_threshold=0.25,
                minimum_confidence=0.70,
                required_consecutive_frames=3,
            ),
            slots=tuple(
                RoiRegion(slot_id=slot_id, x=index * 10, y=0, width=10, height=10)
                for index, slot_id in enumerate(slot_ids)
            ),
        ),
        max_image_bytes=max_image_bytes,
    )


def write_parking_config(path: Path, slot_ids: list[int]) -> None:
    slots = "\n".join(
        f'  - id: {slot_id}\n    name: "S{slot_id}"\n'
        f"    walking_distance: 0.5\n    zone: zone-{slot_id}"
        for slot_id in slot_ids
    )
    path.write_text(f"slots:\n{slots}\n", encoding="utf-8")


def write_roi_config(path: Path, slot_ids: list[int]) -> None:
    path.write_text(
        json.dumps(
            {
                "heuristic": {
                    "edge_threshold": 0.12,
                    "minimum_confidence": 0.70,
                    "required_consecutive_frames": 3,
                },
                "slots": [
                    {"slot_id": slot_id, "x": 0, "y": 0, "width": 10, "height": 10}
                    for slot_id in slot_ids
                ],
            }
        ),
        encoding="utf-8",
    )


def settings_with_roi_ids(
    tmp_path: Path, parking_ids: list[int], roi_ids: list[int]
) -> Settings:
    parking_path = tmp_path / "parking.yaml"
    roi_path = tmp_path / "rois.json"
    write_parking_config(parking_path, parking_ids)
    write_roi_config(roi_path, roi_ids)
    return Settings(parking_config_path=parking_path, roi_config_path=roi_path)


def test_detector_returns_configured_slot_order() -> None:
    observations = detector_for_slots([9, 2]).detect(jpeg_bytes(detector_frame()))

    assert [item.slot_id for item in observations] == [9, 2]


def test_detector_scores_uniform_free_crop_with_full_confidence() -> None:
    observation = detector_for_slots([1]).detect(jpeg_bytes(Image.new("L", (10, 10))))[0]

    assert observation.slot_id == 1
    assert observation.candidate_occupied is False
    assert observation.score == 0.0
    assert observation.confidence == 1.0


def test_detector_scores_patterned_crop_as_occupied() -> None:
    image = Image.new("L", (10, 10))
    for y in range(10):
        for x in range(10):
            image.putpixel((x, y), 255 if (x + y) % 2 else 0)

    observation = detector_for_slots([1]).detect(jpeg_bytes(image))[0]

    assert observation.candidate_occupied is True
    assert observation.score == 0.5
    assert observation.confidence == pytest.approx(1 / 3)


def test_detector_scores_white_single_pixel_as_fully_confident_occupied() -> None:
    detector = HeuristicDetector(
        RoiConfig(
            heuristic=HeuristicConfig(
                edge_threshold=0.25,
                minimum_confidence=0.70,
                required_consecutive_frames=3,
            ),
            slots=(RoiRegion(slot_id=1, x=0, y=0, width=1, height=1),),
        ),
        max_image_bytes=1024 * 1024,
    )

    observation = detector.detect(jpeg_bytes(Image.new("L", (1, 1), color=255)))[0]

    assert observation.candidate_occupied is True
    assert observation.score == 1.0
    assert observation.confidence == 1.0


def test_detector_rejects_valid_non_jpeg_image() -> None:
    stream = BytesIO()
    Image.new("L", (10, 10)).save(stream, format="PNG")

    with pytest.raises(VisionInputError, match="JPEG") as error:
        detector_for_slots([1]).detect(stream.getvalue())

    assert error.value.code == "invalid_image"


def test_detector_rejects_empty_payload() -> None:
    with pytest.raises(VisionInputError, match="empty") as error:
        detector_for_slots([1]).detect(b"")

    assert error.value.code == "empty_image"


def test_detector_rejects_oversized_payload() -> None:
    detector = detector_for_slots([1], max_image_bytes=3)

    with pytest.raises(VisionInputError, match="maximum") as error:
        detector.detect(b"1234")

    assert error.value.code == "image_too_large"


def test_detector_rejects_roi_extending_one_pixel_beyond_image() -> None:
    detector = HeuristicDetector(
        RoiConfig(
            heuristic=HeuristicConfig(
                edge_threshold=0.25,
                minimum_confidence=0.70,
                required_consecutive_frames=3,
            ),
            slots=(RoiRegion(slot_id=1, x=0, y=0, width=11, height=10),),
        ),
        max_image_bytes=1024 * 1024,
    )

    with pytest.raises(VisionInputError, match="slot 1") as error:
        detector.detect(jpeg_bytes(Image.new("L", (10, 10))))

    assert error.value.code == "roi_out_of_bounds"


def test_roi_config_must_match_parking_slots_exactly(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="ROI slot ids must match"):
        settings_with_roi_ids(tmp_path, parking_ids=[2, 9], roi_ids=[2])


def test_settings_reorders_rois_to_match_parking_slot_order(tmp_path: Path) -> None:
    settings = settings_with_roi_ids(tmp_path, parking_ids=[9, 2], roi_ids=[2, 9])

    assert [region.slot_id for region in settings.roi.slots] == [9, 2]
