from __future__ import annotations

import csv
import json
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()

STATIC_DIRECTORY = Path(__file__).resolve().parent.parent / "static"
_TEMPLATE = (STATIC_DIRECTORY / "dashboard.html").read_text(encoding="utf-8")
_PREDICTOR_RESULTS = (
    Path(__file__).resolve().parents[3]
    / "review_outputs/2026-10-15/ml_results/model_comparison.csv"
)


def _load_predictor_results() -> list[dict[str, str | float]]:
    with _PREDICTOR_RESULTS.open(newline="", encoding="utf-8") as results_file:
        return [
            {
                "model": row["model"],
                "mae": float(row["mae"]),
                "mse": float(row["mse"]),
                "rmse": float(row["rmse"]),
                "inference_latency_ms": float(row["inference_latency_ms"]),
            }
            for row in csv.DictReader(results_file)
        ]


def _predictor_rows(results: list[dict[str, str | float]]) -> str:
    rows = []
    for result in results:
        model = str(result["model"])
        label = "Persistence baseline" if model == "persistence_baseline" else model.upper()
        cells = (
            label,
            f"{float(result['mae']):.6f}",
            f"{float(result['mse']):.6f}",
            f"{float(result['rmse']):.6f}",
            f"{float(result['inference_latency_ms']):.6f} ms",
        )
        rows.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>")
    return "".join(rows)


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    predictor_results = _load_predictor_results()
    bootstrap = json.dumps(
        {
            "selected_optimizer": request.app.state.settings.selected_optimizer,
            "selected_predictor": request.app.state.settings.selected_predictor,
            "predictor_comparison": predictor_results,
            "scene": {
                "asset": request.app.state.settings.parking.scene.asset,
                "asset_slot_ids": request.app.state.settings.parking.scene.asset_slot_ids,
                "width": request.app.state.settings.parking.scene.width,
                "center": request.app.state.settings.parking.scene.center.model_dump(),
                "slots": {
                    str(slot.id): slot.scene.model_dump() if slot.scene else None
                    for slot in request.app.state.parking_slots
                },
            },
        }
    )
    return HTMLResponse(
        _TEMPLATE.replace("__DASHBOARD_BOOTSTRAP__", bootstrap)
        .replace("__PREDICTOR_ROWS__", _predictor_rows(predictor_results)),
        headers={"Cache-Control": "no-store, max-age=0"},
    )
