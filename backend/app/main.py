from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from pydantic import BaseModel

from backend.app.config import Settings
from backend.app.db import Database
from backend.app.routes.allocation import router as allocation_router
from backend.app.routes.parking import router as parking_router
from backend.app.services.parking import ParkingService


class HealthResponse(BaseModel):
    status: str
    mode: str
    database: str
    slot_count: int


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
        yield

    application = FastAPI(title="Smart Parking API", version="0.1.0", lifespan=lifespan)
    application.include_router(allocation_router)
    application.include_router(parking_router)

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
