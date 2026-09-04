"""Immutable contracts shared by prediction preprocessing and model trainers."""

from dataclasses import dataclass
from datetime import datetime
from typing import Final

import numpy as np

WEATHER_CATEGORIES: Final = ("clear", "cloudy", "rain", "fog", "storm", "snow", "other")

FEATURE_NAMES: Final = (
    "occupancy_ratio",
    "occupancy_change",
    "occupancy_mean_15m",
    "occupancy_mean_60m",
    "hour_sin",
    "hour_cos",
    "weekday_sin",
    "weekday_cos",
    *(f"weather_{category}" for category in WEATHER_CATEGORIES),
    "holiday",
    "event",
    "entry_count",
    "exit_count",
    "allocation_count",
    "active_session_count",
    "unique_vehicle_count",
    "returning_vehicle_rate",
    "mean_walking_distance",
    "mean_congestion",
    "mean_fairness",
    "allocation_present",
)

CONTINUOUS_FEATURE_NAMES: Final = (
    "occupancy_ratio",
    "occupancy_change",
    "occupancy_mean_15m",
    "occupancy_mean_60m",
    "entry_count",
    "exit_count",
    "allocation_count",
    "active_session_count",
    "unique_vehicle_count",
    "returning_vehicle_rate",
    "mean_walking_distance",
    "mean_congestion",
    "mean_fairness",
)


class PredictionDataError(ValueError):
    """Validation error with a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class PreprocessingConfig:
    interval_minutes: int = 5
    lookback_steps: int = 12
    horizon_steps: int = 1
    train_fraction: float = 0.70
    validation_fraction: float = 0.15
    max_carry_intervals: int = 3

    def __post_init__(self) -> None:
        for name in ("interval_minutes", "lookback_steps", "horizon_steps"):
            value = getattr(self, name)
            if value <= 0:
                raise PredictionDataError("invalid_config", f"{name} must be positive")
        for name in ("train_fraction", "validation_fraction"):
            value = getattr(self, name)
            if not 0 < value < 1:
                raise PredictionDataError(
                    "invalid_config", f"{name} must be strictly between 0 and 1"
                )
        if self.train_fraction + self.validation_fraction >= 1:
            raise PredictionDataError(
                "invalid_config", "train_fraction plus validation_fraction must be less than 1"
            )
        if self.max_carry_intervals < 0:
            raise PredictionDataError("invalid_config", "max_carry_intervals must be non-negative")


@dataclass(frozen=True)
class ContextSampleRecord:
    id: int
    occupancy_count: int
    weather: str
    holiday: int
    event: int
    sampled_at: str


@dataclass(frozen=True)
class SessionRecord:
    id: int
    vehicle_id: int
    entered_at: str
    exited_at: str | None


@dataclass(frozen=True)
class AllocationFeatureRecord:
    id: int
    vehicle_id: int
    created_at: str
    objective_breakdown_json: str


@dataclass(frozen=True)
class PredictionSourceData:
    slot_count: int
    context_samples: tuple[ContextSampleRecord, ...]
    sessions: tuple[SessionRecord, ...]
    allocations: tuple[AllocationFeatureRecord, ...]


@dataclass(frozen=True)
class FeatureBucket:
    timestamp: datetime
    values: tuple[float, ...]


@dataclass(frozen=True)
class ScalerMetadata:
    feature_indices: tuple[int, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]


@dataclass(frozen=True)
class PreparedSplit:
    inputs: np.ndarray
    targets: np.ndarray
    target_timestamps: tuple[datetime, ...]

    def __post_init__(self) -> None:
        inputs = np.array(self.inputs, dtype=np.float64, copy=True)
        targets = np.array(self.targets, dtype=np.float64, copy=True)
        if inputs.ndim != 3:
            raise PredictionDataError(
                "invalid_dataset", "inputs must have shape (examples, lookback, features)"
            )
        if targets.ndim != 1:
            raise PredictionDataError("invalid_dataset", "targets must have shape (examples,)")
        if inputs.shape[0] != targets.shape[0]:
            raise PredictionDataError(
                "invalid_dataset", "inputs and targets must have equal example counts"
            )
        if len(self.target_timestamps) != targets.shape[0]:
            raise PredictionDataError(
                "invalid_dataset", "target timestamp count must match examples"
            )
        if not np.isfinite(inputs).all() or not np.isfinite(targets).all():
            raise PredictionDataError(
                "invalid_dataset", "inputs and targets must contain only finite values"
            )
        if any(
            later < earlier
            for earlier, later in zip(
                self.target_timestamps, self.target_timestamps[1:], strict=False
            )
        ):
            raise PredictionDataError("invalid_dataset", "target timestamps must be chronological")
        inputs.setflags(write=False)
        targets.setflags(write=False)
        object.__setattr__(self, "inputs", inputs)
        object.__setattr__(self, "targets", targets)
        object.__setattr__(self, "target_timestamps", tuple(self.target_timestamps))


@dataclass(frozen=True)
class PreparedDataset:
    feature_names: tuple[str, ...]
    target_name: str
    train: PreparedSplit
    validation: PreparedSplit
    test: PreparedSplit
    scaler: ScalerMetadata
    split_id: str
    source_started_at: datetime
    source_ended_at: datetime
    train_ended_at: datetime
    validation_ended_at: datetime
    config: PreprocessingConfig
    slot_count: int

    def __post_init__(self) -> None:
        if tuple(self.feature_names) != FEATURE_NAMES or self.target_name != "occupancy_ratio":
            raise PredictionDataError(
                "invalid_dataset", "feature names or target name do not match the contract"
            )
        if self.slot_count <= 0:
            raise PredictionDataError("invalid_dataset", "slot_count must be positive")
        splits = (self.train, self.validation, self.test)
        if any(split.inputs.shape[0] == 0 for split in splits):
            raise PredictionDataError(
                "empty_split", "train, validation, and test splits must be non-empty"
            )
        expected = (self.config.lookback_steps, len(FEATURE_NAMES))
        if any(split.inputs.shape[1:] != expected for split in splits):
            raise PredictionDataError(
                "invalid_dataset", "split input shape does not match config and feature contract"
            )
        if not (
            self.source_started_at
            <= self.train_ended_at
            <= self.validation_ended_at
            <= self.source_ended_at
        ):
            raise PredictionDataError(
                "invalid_dataset", "dataset time boundaries must be chronological"
            )
        if any(np.any((split.targets < 0) | (split.targets > 1)) for split in splits):
            raise PredictionDataError(
                "invalid_dataset", "targets must be in the inclusive range [0, 1]"
            )
        if len(self.scaler.feature_indices) != len(self.scaler.means) or len(
            self.scaler.means
        ) != len(self.scaler.scales):
            raise PredictionDataError("invalid_dataset", "scaler metadata lengths must match")
        if any(index < 0 or index >= len(FEATURE_NAMES) for index in self.scaler.feature_indices):
            raise PredictionDataError(
                "invalid_dataset", "scaler feature index is outside the feature contract"
            )
        if not all(
            np.isfinite(value) for value in (*self.scaler.means, *self.scaler.scales)
        ) or any(value <= 0 for value in self.scaler.scales):
            raise PredictionDataError(
                "invalid_dataset", "scaler means and scales must be finite and scales positive"
            )
