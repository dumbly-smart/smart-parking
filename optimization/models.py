from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.config import ObjectiveWeights


class NoAvailableSlotError(RuntimeError):
    """Raised when allocation cannot safely choose a slot."""


class ObjectiveBreakdown(BaseModel):
    model_config = ConfigDict(frozen=True)

    distance: float = Field(ge=0, le=1)
    congestion: float = Field(ge=0, le=1)
    waiting: float = Field(ge=0, le=1)
    fairness: float = Field(ge=0, le=1)


class SlotCandidate(ObjectiveBreakdown):
    slot_id: int = Field(ge=1)
    occupied: bool


class AllocationRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    scenario_id: str = Field(min_length=1, max_length=128)
    candidates: tuple[SlotCandidate, ...]
    weights: ObjectiveWeights = Field(default_factory=ObjectiveWeights)
    seed: int = 42
    iterations: int = Field(default=30, ge=1, le=10_000)

    @field_validator("candidates")
    @classmethod
    def validate_candidates(
        cls, candidates: tuple[SlotCandidate, ...]
    ) -> tuple[SlotCandidate, ...]:
        if not candidates:
            raise ValueError("at least one slot candidate is required")
        if len({candidate.slot_id for candidate in candidates}) != len(candidates):
            raise ValueError("candidate slot ids must be unique")
        return candidates


class AllocationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    algorithm: str
    scenario_id: str
    chosen_slot_id: int = Field(ge=1)
    best_cost: float = Field(ge=0, le=1)
    iterations: int = Field(ge=1)
    runtime_ms: float = Field(ge=0)
    objective_breakdown: ObjectiveBreakdown
    seed: int


class PersistedOptimizerRun(AllocationResult):
    created_at: str


class Optimizer(Protocol):
    name: str

    def optimize(self, request: AllocationRequest) -> AllocationResult: ...
