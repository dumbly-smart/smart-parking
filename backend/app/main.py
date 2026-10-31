from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from hmac import compare_digest
import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.app.config import Settings, SlotConfig
from backend.app.db import Database
from backend.app.routes.allocation import router as allocation_router
from backend.app.routes.dashboard import STATIC_DIRECTORY
from backend.app.routes.dashboard import router as dashboard_router
from backend.app.routes.parking import router as parking_router
from backend.app.routes.prediction import router as prediction_router
from backend.app.routes.sumo import router as sumo_router
from backend.app.services.parking import ParkingService
from backend.app.services.prediction import PredictionService
from backend.app.services.sumo import SumoService
from backend.app.services.parking_traffic import ParkingTraffic


class HealthResponse(BaseModel):
    status: str
    mode: str
    database: str
    slot_count: int


class DashboardStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: dict[str, object]) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return response


def create_app(settings: Settings | None = None) -> FastAPI:
    application_settings = settings or Settings()
    database = Database(application_settings.database_path)
    configured_slots = list(application_settings.parking.slots)
    try:
        garage_layout = json.loads(application_settings.sumo_map_path.read_text())
    except (OSError, ValueError):
        garage_layout = {}
    if settings is None and len(garage_layout.get("floors", ())) == 6:
        configured_by_id = {slot.id: slot for slot in configured_slots}
        live_ids = {int(bay["live_slot_id"]) for floor in garage_layout["floors"] for bay in floor["bays"] if bay.get("live_slot_id") is not None}
        next_id = max(configured_by_id, default=0) + 1
        for floor in garage_layout["floors"]:
            for index, bay in enumerate(floor["bays"], start=1):
                if bay.get("live_slot_id") is not None:
                    continue
                while next_id in live_ids or next_id in configured_by_id:
                    next_id += 1
                configured_by_id[next_id] = SlotConfig(
                    id=next_id,
                    name=f"L{floor['number']}-{bay.get('zone', 'P')}-{index:03}",
                    walking_distance=0.5,
                    zone=f"L{floor['number']}-{bay.get('zone', 'P')}",
                )
                next_id += 1
        configured_slots = sorted(configured_by_id.values(), key=lambda slot: slot.id)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        database.initialize(configured_slots)
        application.state.parking_slots = tuple(configured_slots)
        application.state.settings = application_settings
        application.state.database = database
        application.state.parking_service = ParkingService(
            database,
            application_settings.selected_optimizer,
            application_settings.parking.allocation.weights,
        )
        application.state.prediction_service = PredictionService(
            database,
            application_settings.selected_predictor,
            application_settings.prediction_artifact_directory,
        )
        application.state.sumo_service = SumoService(
            application_settings.sumo_binary,
            application_settings.sumo_config_path,
            application_settings.sumo_step_length,
            ground_floor=int(garage_layout.get("ground_floor", 1)),
            floor_height=float(garage_layout.get("floor_height", 4.2)),
        )
        application.state.sumo_service.parking_traffic = ParkingTraffic(application.state.parking_service)
        try:
            yield
        finally:
            application.state.sumo_service.close()
            application.state.sumo_service.parking_traffic.close()

    application = FastAPI(title="Smart Parking API", version="0.1.0", lifespan=lifespan)

    @application.middleware("http")
    async def device_api_auth(request: Request, call_next):
        token = application_settings.device_api_token
        if token is not None and request.url.path.startswith("/api/"):
            expected = f"Bearer {token.get_secret_value()}"
            received = request.headers.get("authorization", "")
            if not compare_digest(received, expected):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "device authentication required"},
                    headers={"WWW-Authenticate": "Bearer"},
                )
        return await call_next(request)

    application.mount("/static", DashboardStaticFiles(directory=STATIC_DIRECTORY), name="static")
    application.include_router(allocation_router)
    application.include_router(dashboard_router)
    application.include_router(parking_router)
    application.include_router(prediction_router)
    application.include_router(sumo_router)

    @application.get("/health", response_model=HealthResponse)
    def health(request: Request) -> HealthResponse:
        count = request.app.state.database.slot_count()
        return HealthResponse(
            status="ok" if count == len(request.app.state.parking_slots) else "degraded",
            mode=request.app.state.settings.mode,
            database="ok",
            slot_count=count,
        )

    return application


app = create_app()
