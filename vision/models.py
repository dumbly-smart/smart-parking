from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class HeuristicConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    edge_threshold: float = Field(gt=0, lt=1)
    minimum_confidence: float = Field(ge=0, le=1)
    required_consecutive_frames: int = Field(ge=1)


class RoiRegion(BaseModel):
    model_config = ConfigDict(frozen=True)

    slot_id: int = Field(ge=1)
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class RoiConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    heuristic: HeuristicConfig
    slots: tuple[RoiRegion, ...]

    @field_validator("slots")
    @classmethod
    def non_empty_unique_slot_ids(cls, slots: tuple[RoiRegion, ...]) -> tuple[RoiRegion, ...]:
        if not slots:
            raise ValueError("at least one ROI slot is required")
        if len({slot.slot_id for slot in slots}) != len(slots):
            raise ValueError("ROI slot ids must be unique")
        return slots


class DetectorObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    slot_id: int = Field(ge=1)
    candidate_occupied: bool
    score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
