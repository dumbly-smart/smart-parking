from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile

from backend.app.models.occupancy import OccupancyUpdateResponse
from vision.detector import VisionInputError

router = APIRouter()


@router.post("/api/camera/occupancy", response_model=OccupancyUpdateResponse)
async def update_occupancy(
    request: Request,
    image: Annotated[UploadFile, File()],
    response: Response,
) -> OccupancyUpdateResponse:
    maximum = request.app.state.settings.camera_max_image_bytes
    payload = await image.read(maximum + 1)
    try:
        started = time.perf_counter()
        result = request.app.state.occupancy_service.process(payload)
        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers["Server-Timing"] = f"camera_process;dur={elapsed_ms:.3f}"
        response.headers["X-Camera-Processing-Ms"] = f"{elapsed_ms:.3f}"
        return result
    except VisionInputError as exc:
        status_code = 413 if exc.code == "image_too_large" else 400
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
