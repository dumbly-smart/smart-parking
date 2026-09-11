from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

router = APIRouter()


class PredictionResponse(BaseModel):
    model: Literal["baseline", "lstm", "gru", "transformer"]
    occupancy_ratio: float = Field(ge=0, le=1)
    target_at: datetime
    fallback_reason: str | None = None


class PredictorBenchmark(BaseModel):
    model: Literal["lstm", "gru", "transformer"]
    split_id: str
    mae: float = Field(ge=0)
    mse: float = Field(ge=0)
    rmse: float = Field(ge=0)
    inference_latency_ms: float = Field(ge=0)
    artifact_sha256: str
    created_at: str


class PredictorBenchmarksResponse(BaseModel):
    runs: list[PredictorBenchmark]


@router.get("/api/prediction", response_model=PredictionResponse)
def prediction(request: Request) -> PredictionResponse:
    forecast = request.app.state.prediction_service.forecast()
    return PredictionResponse(
        model=forecast.model,
        occupancy_ratio=forecast.occupancy_ratio,
        target_at=forecast.target_at,
        fallback_reason=forecast.fallback_reason,
    )


@router.get("/api/benchmarks/predictors", response_model=PredictorBenchmarksResponse)
def predictor_benchmarks(request: Request) -> PredictorBenchmarksResponse:
    return PredictorBenchmarksResponse(
        runs=[
            PredictorBenchmark(
                model=run.model.value,
                split_id=run.split_id,
                mae=run.metrics.mae,
                mse=run.metrics.mse,
                rmse=run.metrics.rmse,
                inference_latency_ms=run.metrics.inference_latency_ms,
                artifact_sha256=run.artifact_sha256,
                created_at=run.created_at,
            )
            for run in request.app.state.database.list_prediction_results()
        ]
    )
