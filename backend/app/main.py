from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from hmac import compare_digest

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.app.config import Settings
from backend.app.db import Database
from backend.app.routes.allocation import router as allocation_router
from backend.app.routes.dashboard import STATIC_DIRECTORY
from backend.app.routes.dashboard import router as dashboard_router
from backend.app.routes.occupancy import router as occupancy_router
from backend.app.routes.parking import router as parking_router
from backend.app.routes.prediction import router as prediction_router
from backend.app.services.occupancy import OccupancyService
from backend.app.services.parking import ParkingService
from backend.app.services.prediction import PredictionService
from vision.detector import HeuristicDetector


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

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        database.initialize(application_settings.parking.slots)
        application.state.settings = application_settings
        application.state.database = database
        application.state.parking_service = ParkingService(
            database,
            application_settings.selected_optimizer,
            application_settings.parking.allocation.weights,
        )
        detector = HeuristicDetector(
            application_settings.roi,
            max_image_bytes=application_settings.camera_max_image_bytes,
        )
        application.state.occupancy_service = OccupancyService(
            database,
            detector,
            minimum_confidence=application_settings.roi.heuristic.minimum_confidence,
            required_consecutive_frames=(
                application_settings.roi.heuristic.required_consecutive_frames
            ),
        )
        application.state.prediction_service = PredictionService(
            database,
            application_settings.selected_predictor,
            application_settings.prediction_artifact_directory,
        )
        yield

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
    application.include_router(occupancy_router)
    application.include_router(parking_router)
    application.include_router(prediction_router)

    @application.get("/health", response_model=HealthResponse)
    def health(request: Request) -> HealthResponse:
        count = request.app.state.database.slot_count()
        return HealthResponse(
            status="ok" if count == len(request.app.state.settings.parking.slots) else "degraded",
            mode=request.app.state.settings.mode,
            database="ok",
            slot_count=count,
        )

    return application


app = create_app()
