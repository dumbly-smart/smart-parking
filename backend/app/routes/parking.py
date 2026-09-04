from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from backend.app.models.parking import EntryResponse, ParkingConflict, VehicleOperationRequest
from optimization.models import NoAvailableSlotError

router = APIRouter()


@router.post("/api/vehicle/entry", response_model=EntryResponse)
def enter_vehicle(payload: VehicleOperationRequest, request: Request) -> EntryResponse:
    try:
        return request.app.state.parking_service.enter(payload)
    except ParkingConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except NoAvailableSlotError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "no_available_slot", "message": str(exc)},
        ) from exc
