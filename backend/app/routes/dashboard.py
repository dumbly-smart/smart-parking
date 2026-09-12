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
        }
    )
    return HTMLResponse(_TEMPLATE.replace("__DASHBOARD_BOOTSTRAP__", bootstrap))
