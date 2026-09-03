from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from pydantic import BaseModel

from backend.app.config import Settings
from backend.app.db import Database


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
        yield

    application = FastAPI(title="Smart Parking API", version="0.1.0", lifespan=lifespan)

    @application.get("/health", response_model=HealthResponse)
    def health(request: Request) -> HealthResponse:
        count = request.app.state.database.slot_count()
        return HealthResponse(
            status="ok" if count == 5 else "degraded",
            mode=request.app.state.settings.mode,
            database="ok",
            slot_count=count,
        )

    return application


app = create_app()
