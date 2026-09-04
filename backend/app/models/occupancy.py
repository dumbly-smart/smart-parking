from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class OccupancyTransition(BaseModel):
    model_config = ConfigDict(frozen=True)

    slot_id: int = Field(ge=1)
    occupied: bool
    confidence: float = Field(ge=0, le=1)


class SlotOccupancyResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    slot_id: int = Field(ge=1)
    candidate_occupied: bool
    accepted_occupied: bool
    score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    outcome: Literal["unchanged", "pending", "accepted", "blocked"]
    consecutive_frames: int = Field(ge=0)


class OccupancyUpdateResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    detector: Literal["heuristic"] = "heuristic"
    observed_at: str
    slots: tuple[SlotOccupancyResult, ...]
