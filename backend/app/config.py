from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from vision.models import RoiConfig


class ObjectiveWeights(BaseModel):
    model_config = ConfigDict(frozen=True)

    distance: float = Field(default=0.35, ge=0, le=1)
    congestion: float = Field(default=0.30, ge=0, le=1)
    waiting: float = Field(default=0.20, ge=0, le=1)
    fairness: float = Field(default=0.15, ge=0, le=1)

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> ObjectiveWeights:
        if abs(sum(self.model_dump().values()) - 1.0) > 1e-9:
            raise ValueError("allocation weights must sum to 1.0")
        return self


class AllocationConfig(BaseModel):
    weights: ObjectiveWeights = Field(default_factory=ObjectiveWeights)


class SlotConfig(BaseModel):
    id: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=32)
    walking_distance: float = Field(ge=0, le=1)
    zone: str = Field(min_length=1, max_length=32)


class ParkingConfig(BaseModel):
    allocation: AllocationConfig = Field(default_factory=AllocationConfig)
    slots: list[SlotConfig]

    @field_validator("slots")
    @classmethod
    def non_empty_unique_slots(cls, slots: list[SlotConfig]) -> list[SlotConfig]:
        if not slots:
            raise ValueError("at least one parking slot is required")
        if len({slot.id for slot in slots}) != len(slots):
            raise ValueError("parking slot ids must be unique")
        if len({slot.name for slot in slots}) != len(slots):
            raise ValueError("parking slot names must be unique")
        return slots


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="SMART_PARKING_",
        extra="ignore",
    )

    mode: Literal["demo", "hardware"] = "demo"
    database_url: str = "sqlite:///./data/parking.db"
    parking_config_path: Path = Path("config/parking.yaml")
    roi_config_path: Path = Path("config/rois.example.json")
    camera_max_image_bytes: int = Field(default=5 * 1024 * 1024, gt=0)
    selected_optimizer: Literal["ga", "pso", "aco"] = "ga"
    selected_predictor: Literal["baseline", "lstm", "gru", "transformer"] = "baseline"
    prediction_artifact_directory: Path = Path("artifacts/prediction")
    hardware_enabled: bool = False
    _parking: ParkingConfig = PrivateAttr()
    _roi: RoiConfig = PrivateAttr()

    def __init__(self, **values: object) -> None:
        super().__init__(**values)
        try:
            raw = yaml.safe_load(self.parking_config_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise ValueError(f"cannot load parking configuration: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError("parking configuration must be a mapping")
        self._parking = ParkingConfig.model_validate(raw)
        try:
            raw_roi = json.loads(self.roi_config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot load ROI configuration: {exc}") from exc
        if not isinstance(raw_roi, dict):
            raise ValueError("ROI configuration must be a mapping")
        roi = RoiConfig.model_validate(raw_roi)
        roi_regions = {region.slot_id: region for region in roi.slots}
        parking_slot_ids = [slot.id for slot in self._parking.slots]
        if set(roi_regions) != set(parking_slot_ids):
            raise ValueError("ROI slot ids must match parking slot ids exactly")
        self._roi = roi.model_copy(
            update={"slots": tuple(roi_regions[slot_id] for slot_id in parking_slot_ids)}
        )
        if self.mode == "hardware" and not self.hardware_enabled:
            raise ValueError("hardware mode requires SMART_PARKING_HARDWARE_ENABLED=true")

    @property
    def parking(self) -> ParkingConfig:
        return self._parking

    @property
    def roi(self) -> RoiConfig:
        return self._roi

    @property
    def database_path(self) -> Path:
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            raise ValueError("only sqlite:/// database URLs are supported")
        value = self.database_url.removeprefix(prefix)
        if not value:
            raise ValueError("SQLite database path cannot be empty")
        return Path(value)
