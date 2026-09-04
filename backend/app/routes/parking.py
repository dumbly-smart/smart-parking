from fastapi import APIRouter, HTTPException, Request

from backend.app.models.parking import EntryResponse, ParkingConflict, VehicleOperationRequest
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
