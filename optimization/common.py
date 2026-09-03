from __future__ import annotations

from collections.abc import Sequence
from time import perf_counter

from optimization.fitness import weighted_cost
from optimization.models import (
    AllocationRequest,
    AllocationResult,
    NoAvailableSlotError,
    SlotCandidate,
)


def available_candidates(request: AllocationRequest) -> tuple[SlotCandidate, ...]:
    available = tuple(candidate for candidate in request.candidates if not candidate.occupied)
    if not available:
        raise NoAvailableSlotError("no parking slot is available")
    return available


def best_candidate(
    candidates: Sequence[SlotCandidate], request: AllocationRequest
) -> SlotCandidate:
    return min(candidates, key=lambda item: (weighted_cost(item, request.weights)[0], item.slot_id))


def result_for(
    algorithm: str,
    request: AllocationRequest,
    candidate: SlotCandidate,
    started_at: float,
) -> AllocationResult:
    cost, breakdown = weighted_cost(candidate, request.weights)
    return AllocationResult(
        algorithm=algorithm,
        scenario_id=request.scenario_id,
        chosen_slot_id=candidate.slot_id,
        best_cost=cost,
        iterations=request.iterations,
        runtime_ms=(perf_counter() - started_at) * 1000,
        objective_breakdown=breakdown,
        seed=request.seed,
    )
