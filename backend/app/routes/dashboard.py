from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()

STATIC_DIRECTORY = Path(__file__).resolve().parent.parent / "static"
_TEMPLATE = (STATIC_DIRECTORY / "dashboard.html").read_text(encoding="utf-8")


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    bootstrap = json.dumps(
        {
            "selected_optimizer": request.app.state.settings.selected_optimizer,
            "selected_predictor": request.app.state.settings.selected_predictor,
            "scene": {
                "asset": request.app.state.settings.parking.scene.asset,
                "asset_slot_ids": request.app.state.settings.parking.scene.asset_slot_ids,
                "width": request.app.state.settings.parking.scene.width,
                "slots": {
                    str(slot.id): slot.scene.model_dump() if slot.scene else None
                    for slot in request.app.state.settings.parking.slots
                },
            },
        }
    )
    return HTMLResponse(
        _TEMPLATE.replace("__DASHBOARD_BOOTSTRAP__", bootstrap),
        headers={"Cache-Control": "no-store, max-age=0"},
    )
