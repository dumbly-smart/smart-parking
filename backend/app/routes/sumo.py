from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from backend.app.models.sumo import SumoMapResponse, SumoStatusResponse

router = APIRouter(prefix="/api/sumo", tags=["sumo"])


@router.get("/status", response_model=SumoStatusResponse)
def sumo_status(request: Request) -> SumoStatusResponse:
    return SumoStatusResponse.model_validate(request.app.state.sumo_service.status())


@router.post("/start", response_model=SumoStatusResponse)
def start_sumo(request: Request) -> SumoStatusResponse:
    return SumoStatusResponse.model_validate(request.app.state.sumo_service.start())


@router.post("/stop", response_model=SumoStatusResponse)
def stop_sumo(request: Request) -> SumoStatusResponse:
    return SumoStatusResponse.model_validate(request.app.state.sumo_service.stop())


@router.post("/pause", response_model=SumoStatusResponse)
def pause_sumo(request: Request) -> SumoStatusResponse:
    return SumoStatusResponse.model_validate(request.app.state.sumo_service.pause())


@router.post("/resume", response_model=SumoStatusResponse)
def resume_sumo(request: Request) -> SumoStatusResponse:
    return SumoStatusResponse.model_validate(request.app.state.sumo_service.resume())


@router.post("/reset", response_model=SumoStatusResponse)
def reset_sumo(request: Request) -> SumoStatusResponse:
    return SumoStatusResponse.model_validate(request.app.state.sumo_service.reset())


@router.get("/map", response_model=SumoMapResponse)
def sumo_map(request: Request) -> SumoMapResponse:
    path: Path = request.app.state.settings.sumo_map_path
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return SumoMapResponse.model_validate(data)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise HTTPException(
            status_code=503,
            detail={"code": "map_unavailable", "message": f"Garage layout data is unavailable: {error}"},
        ) from error
