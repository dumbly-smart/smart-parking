from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from optimization.benchmark import BenchmarkRunner
from optimization.models import (
    AllocationRequest,
    AllocationResult,
    NoAvailableSlotError,
    PersistedOptimizerRun,
)

router = APIRouter()


class AllocationRunRequest(BaseModel):
    algorithm: Literal["ga", "pso", "aco", "all"] = "all"
    request: AllocationRequest


class AllocationRunResponse(BaseModel):
    results: list[AllocationResult]


class OptimizerBenchmarksResponse(BaseModel):
    runs: list[PersistedOptimizerRun]


@router.post("/api/allocation/run", response_model=AllocationRunResponse)
def run_allocation(payload: AllocationRunRequest, request: Request) -> AllocationRunResponse:
    algorithms = ("ga", "pso", "aco") if payload.algorithm == "all" else (payload.algorithm,)
    try:
        results = BenchmarkRunner(request.app.state.database).run(
            payload.request, algorithms
        )
    except NoAvailableSlotError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "no_available_slot", "message": str(exc)},
        ) from exc
    return AllocationRunResponse(results=results)


@router.get("/api/benchmarks/optimizers", response_model=OptimizerBenchmarksResponse)
def optimizer_benchmarks(request: Request) -> OptimizerBenchmarksResponse:
    return OptimizerBenchmarksResponse(runs=request.app.state.database.list_optimizer_results())
