from fastapi import APIRouter, HTTPException, Request

from backend.app.models.parking import (
    EntryResponse,
    ExitResponse,
    ParkingConflict,
    ParkingStatusResponse,
    VehicleOperationRequest,
)
from optimization.models import NoAvailableSlotError

router = APIRouter()


@router.post("/api/vehicle/entry", response_model=EntryResponse)
def enter_vehicle(payload: VehicleOperationRequest, request: Request) -> EntryResponse:
    try:
        return request.app.state.parking_service.enter(payload)
    except (ParkingConflict, NoAvailableSlotError) as exc:
        code = exc.code if isinstance(exc, ParkingConflict) else "no_available_slot"
        raise HTTPException(
            status_code=409, detail={"code": code, "message": str(exc)}
        ) from exc


@router.post("/api/vehicle/exit", response_model=ExitResponse)
def exit_vehicle(payload: VehicleOperationRequest, request: Request) -> ExitResponse:
    try:
        return request.app.state.parking_service.exit(payload)
    except ParkingConflict as exc:
        raise HTTPException(
            status_code=409, detail={"code": exc.code, "message": exc.message}
        ) from exc


@router.get("/api/parking/status", response_model=ParkingStatusResponse)
def parking_status(request: Request) -> ParkingStatusResponse:
    return request.app.state.parking_service.status()
