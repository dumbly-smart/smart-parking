from __future__ import annotations

from io import BytesIO

import numpy as np
from PIL import Image, ImageFilter, UnidentifiedImageError

from vision.models import DetectorObservation, RoiConfig, RoiRegion


class VisionInputError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class HeuristicDetector:
    def __init__(self, roi_config: RoiConfig, *, max_image_bytes: int) -> None:
        if max_image_bytes <= 0:
            raise ValueError("max_image_bytes must be positive")
        self._roi_config = roi_config
        self.max_image_bytes = max_image_bytes

    def detect(self, image_bytes: bytes) -> tuple[DetectorObservation, ...]:
        if not image_bytes:
            raise VisionInputError("empty_image", "image payload is empty")
        if len(image_bytes) > self.max_image_bytes:
            raise VisionInputError("image_too_large", "image payload exceeds maximum size")

        image = self._decode_jpeg(image_bytes)
        try:
            self._validate_roi_bounds(image)
            return tuple(self._detect_region(image, region) for region in self._roi_config.slots)
        finally:
            image.close()

    @staticmethod
    def _decode_jpeg(image_bytes: bytes) -> Image.Image:
        try:
            with Image.open(BytesIO(image_bytes)) as verified_image:
                verified_image.verify()
            image = Image.open(BytesIO(image_bytes))
            if image.format != "JPEG":
                image.close()
                raise VisionInputError("invalid_image", "image payload must be a valid JPEG")
            image.load()
            return image
        except VisionInputError:
            raise
        except (Image.DecompressionBombError, OSError, SyntaxError, UnidentifiedImageError) as exc:
            raise VisionInputError("invalid_image", "image payload must be a valid JPEG") from exc

    def _validate_roi_bounds(self, image: Image.Image) -> None:
        for region in self._roi_config.slots:
            if region.x + region.width > image.width or region.y + region.height > image.height:
                raise VisionInputError(
                    "roi_out_of_bounds",
                    f"ROI for slot {region.slot_id} extends outside image bounds",
                )

    def _detect_region(self, image: Image.Image, region: RoiRegion) -> DetectorObservation:
        crop = image.crop((region.x, region.y, region.x + region.width, region.y + region.height))
        edges = crop.convert("L").filter(ImageFilter.FIND_EDGES)
        pixels = np.asarray(edges, dtype=np.uint8)
        score = float(np.count_nonzero(pixels >= 128) / pixels.size)
        threshold = self._roi_config.heuristic.edge_threshold
        occupied = score >= threshold
        confidence = (
            (score - threshold) / (1.0 - threshold)
            if occupied
            else 1.0 - score / threshold
        )
        confidence = min(max(confidence, 0.0), 1.0)
        return DetectorObservation(
            slot_id=region.slot_id,
            candidate_occupied=occupied,
            score=score,
            confidence=confidence,
        )
