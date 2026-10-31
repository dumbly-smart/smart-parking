from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.responses import HTMLResponse
from fastapi.responses import Response

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


@router.get("/receipt/{session_id}", response_class=HTMLResponse)
def parking_receipt(session_id: int, request: Request) -> HTMLResponse:
    details = request.app.state.database.parking_receipt(session_id)
    if details is None:
        raise HTTPException(status_code=404, detail="Parking receipt not found")
    import html
    escaped = {key: html.escape(str(value or "—")) for key, value in details.items()}
    amount = int(details["amount_due_paise"] or 0) / 100
    state = "PAID" if details["exited_at"] else "PARKED · LIVE ESTIMATE"
    body = f'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Parkflow receipt</title><style>body{{margin:0;background:#0b1820;color:#e8f2ee;font:16px system-ui;display:grid;place-items:center;min-height:100vh}}main{{width:min(520px,90vw);background:#14262d;padding:28px;border-radius:20px}}h1{{margin:4px 0 20px}}dl{{display:grid;grid-template-columns:1fr auto;gap:14px}}dt{{color:#a8bbb5}}dd{{margin:0;text-align:right}}.amount{{font-size:2rem;color:#75e3b2}}small{{color:#a8bbb5}}</style></head><body><main><small>PARKFLOW · PARKING SESSION #{escaped['session_id']}</small><h1>{state}</h1><dl><dt>Vehicle</dt><dd>{escaped['rfid_uid']}</dd><dt>Bay</dt><dd>{escaped['slot_name']}</dd><dt>Entry</dt><dd>{escaped['entered_at']}</dd><dt>Exit</dt><dd>{escaped['exited_at']}</dd><dt>Duration</dt><dd>{int(details['duration_seconds'])//3600}h {int(details['duration_seconds'])%3600//60}m</dd><dt>Rate</dt><dd>₹50 first hour, ₹40 each additional started hour</dd><dt>Grace period</dt><dd>First 10 minutes free</dd><dt>Daily maximum</dt><dd>₹400 per 24-hour period</dd></dl><h2 class="amount">₹{amount:.2f}</h2><small>Live estimate until exit. Final charge uses the recorded exit time.</small></main></body></html>'''
    return HTMLResponse(body, headers={"Cache-Control": "no-store"})


@router.get("/api/parking/sessions/{session_id}")
def parking_receipt_data(session_id: int, request: Request) -> dict[str, object]:
    details = request.app.state.database.parking_receipt(session_id)
    if details is None:
        raise HTTPException(status_code=404, detail="Parking receipt not found")
    details["receipt_url"] = f"/receipt/{session_id}"
    return details


@router.get("/api/parking/sessions/{session_id}/qr")
def parking_receipt_qr(session_id: int, request: Request) -> Response:
    from io import BytesIO
    import qrcode
    if request.app.state.database.parking_receipt(session_id) is None:
        raise HTTPException(status_code=404, detail="Parking receipt not found")
    url = str(request.base_url).rstrip("/") + f"/receipt/{session_id}"
    image = qrcode.make(url)
    output = BytesIO()
    image.save(output, format="PNG")
    return Response(output.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})


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


@router.get("/api/parking/device-status")
def device_parking_status(request: Request, rfid_uid: str | None = None) -> dict[str, object]:
    status = request.app.state.parking_service.status()
    uid = (rfid_uid or "").strip().upper()
    vehicle = next((slot.model_dump() for slot in status.slots if slot.occupied and slot.rfid_uid == uid), None)
    return {"slots": [slot.model_dump() for slot in status.slots if slot.id <= 5], "vehicle": vehicle, "event_cursor": status.event_cursor}


@router.post("/api/parking/hardware-events")
def record_hardware_event(payload: HardwareEventRequest, request: Request) -> dict[str, object]:
    try:
        return request.app.state.database.record_hardware_event(
            payload.event_type, payload.operation, payload.operation_key, payload.rfid_uid
        )
    except ParkingConflict as exc:
        raise HTTPException(
            status_code=409, detail={"code": exc.code, "message": exc.message}
        ) from exc


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
                    public_event = {key: value for key, value in event.items() if key != "rfid_uid"}
                    yield f"id: {cursor}\nevent: parking\ndata: {json.dumps(public_event)}\n\n"
            else:
                yield ": heartbeat\n\n"
                await asyncio.sleep(1)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
