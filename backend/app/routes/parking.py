from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend.app.models.parking import (
    EntryResponse,
    ExitResponse,
    HardwareEventRequest,
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


@router.post("/api/vehicle/exit", response_model=ExitResponse)
def exit_vehicle(payload: VehicleOperationRequest, request: Request) -> ExitResponse:
    try:
        return request.app.state.parking_service.exit(payload)
    except ParkingConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message},
        ) from exc


@router.get("/api/parking/status", response_model=ParkingStatusResponse)
def parking_status(request: Request) -> ParkingStatusResponse:
    return request.app.state.parking_service.status()


@router.post("/api/parking/hardware-events")
def record_hardware_event(payload: HardwareEventRequest, request: Request) -> dict[str, object]:
    try:
        return request.app.state.database.record_hardware_event(
            payload.event_type, payload.operation, payload.operation_key, payload.rfid_uid
        )
    except ParkingConflict as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": exc.message}) from exc


@router.get("/api/parking/events/stream")
async def parking_event_stream(request: Request, since_id: int = 0) -> StreamingResponse:
    last_id = request.headers.get("last-event-id")
    cursor = max(0, int(last_id) if last_id and last_id.isdecimal() else since_id)

    async def events():
        nonlocal cursor
        while not await request.is_disconnected():
            batch = await asyncio.to_thread(request.app.state.database.parking_events_after, cursor)
            if batch:
                for event in batch:
                    cursor = int(event["id"])
                    yield f"id: {cursor}\nevent: parking\ndata: {json.dumps(event)}\n\n"
            else:
                yield ": heartbeat\n\n"
                await asyncio.sleep(1)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
