"""Deterministic aggregation and feature engineering for prediction inputs."""

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

import numpy as np

from prediction.models import (
    CONTINUOUS_FEATURE_NAMES,
    FEATURE_NAMES,
    TARGET_NAME,
    WEATHER_CATEGORIES,
    AllocationFeatureRecord,
    ContextSampleRecord,
    FeatureBucket,
    PredictionDataError,
    PredictionSourceData,
    PreparedDataset,
    PreparedSplit,
    PreprocessingConfig,
    ScalerMetadata,
    SessionRecord,
)


@dataclass(frozen=True)
class _ParsedContext:
    record: ContextSampleRecord
    sampled_at: datetime


@dataclass(frozen=True)
class _ParsedSession:
    record: SessionRecord
    entered_at: datetime
    exited_at: datetime | None


@dataclass(frozen=True)
class _ParsedAllocation:
    record: AllocationFeatureRecord
    created_at: datetime
    objectives: tuple[float, float, float]


@dataclass(frozen=True)
class RuntimeInput:
    """One scaled shared-contract input window for the next five-minute bucket."""

    inputs: np.ndarray
    target_at: datetime
    latest_occupancy_ratio: float

    def __post_init__(self) -> None:
        inputs = np.array(self.inputs, dtype=np.float64, copy=True)
        if inputs.shape != (1, 12, len(FEATURE_NAMES)) or not np.isfinite(inputs).all():
            raise PredictionDataError(
                "invalid_runtime_input", "runtime inputs must match the fixed prediction contract"
            )
        if self.target_at.tzinfo is None or self.target_at.utcoffset() != timedelta(0):
            raise PredictionDataError("invalid_runtime_input", "runtime target must be UTC")
        if self.target_at.second or self.target_at.microsecond or self.target_at.minute % 5:
            raise PredictionDataError(
                "invalid_runtime_input", "runtime target must align to five-minute buckets"
            )
        if (
            not math.isfinite(self.latest_occupancy_ratio)
            or not 0 <= self.latest_occupancy_ratio <= 1
        ):
            raise PredictionDataError(
                "invalid_runtime_input", "latest occupancy ratio must be within [0, 1]"
            )
        inputs.setflags(write=False)
        object.__setattr__(self, "inputs", inputs)


def parse_utc_timestamp(value: str, field: str) -> datetime:
    """Parse an ISO-8601 timestamp, require an offset, and normalize it to UTC."""
    try:
        normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
        timestamp = datetime.fromisoformat(normalized)
    except (AttributeError, TypeError, ValueError) as error:
        raise PredictionDataError(
            "invalid_timestamp", f"{field} must be a valid ISO-8601 timestamp"
        ) from error
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise PredictionDataError(
            "invalid_timestamp", f"{field} must include a timezone offset"
        )
    return timestamp.astimezone(UTC)


def _floor_timestamp(timestamp: datetime, interval_seconds: int) -> datetime:
    epoch_seconds = math.floor(timestamp.timestamp())
    bucket_seconds = epoch_seconds - epoch_seconds % interval_seconds
    return datetime.fromtimestamp(bucket_seconds, tz=UTC)


def _require_unique_ids(
    records: (
        tuple[ContextSampleRecord, ...]
        | tuple[SessionRecord, ...]
        | tuple[AllocationFeatureRecord, ...]
    ),
    collection: str,
) -> None:
    record_ids = [record.id for record in records]
    if len(record_ids) != len(set(record_ids)):
        raise PredictionDataError("duplicate_id", f"{collection} contains duplicate record IDs")


def _parse_contexts(
    source: PredictionSourceData,
) -> tuple[_ParsedContext, ...]:
    _require_unique_ids(source.context_samples, "context samples")
    parsed: list[_ParsedContext] = []
    for record in source.context_samples:
        if (
            not isinstance(record.occupancy_count, int)
            or isinstance(record.occupancy_count, bool)
            or not 0 <= record.occupancy_count <= source.slot_count
        ):
            raise PredictionDataError(
                "invalid_occupancy", "occupancy count must be within the configured slot range"
            )
        if record.holiday not in (0, 1) or record.event not in (0, 1):
            raise PredictionDataError("invalid_flag", "holiday and event flags must be 0 or 1")
        parsed.append(
            _ParsedContext(
                record=record,
                sampled_at=parse_utc_timestamp(record.sampled_at, "sampled_at"),
            )
        )
    return tuple(sorted(parsed, key=lambda item: (item.sampled_at, item.record.id)))


def _parse_sessions(source: PredictionSourceData) -> tuple[_ParsedSession, ...]:
    _require_unique_ids(source.sessions, "sessions")
    parsed: list[_ParsedSession] = []
    for record in source.sessions:
        entered_at = parse_utc_timestamp(record.entered_at, "entered_at")
        exited_at = (
            parse_utc_timestamp(record.exited_at, "exited_at")
            if record.exited_at is not None
            else None
        )
        if exited_at is not None and exited_at < entered_at:
            raise PredictionDataError("invalid_session", "session exit cannot precede entry")
        parsed.append(_ParsedSession(record, entered_at, exited_at))
    return tuple(sorted(parsed, key=lambda item: (item.entered_at, item.record.id)))


def _parse_allocations(source: PredictionSourceData) -> tuple[_ParsedAllocation, ...]:
    _require_unique_ids(source.allocations, "allocations")
    parsed: list[_ParsedAllocation] = []
    for record in source.allocations:
        created_at = parse_utc_timestamp(record.created_at, "created_at")
        try:
            payload = json.loads(record.objective_breakdown_json)
            values = tuple(
                float(payload[key]) for key in ("distance", "congestion", "fairness")
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, OverflowError) as error:
            raise PredictionDataError(
                "invalid_objective",
                "objective breakdown must contain numeric distance, congestion, and fairness",
            ) from error
        if not all(math.isfinite(value) and 0 <= value <= 1 for value in values):
            raise PredictionDataError(
                "invalid_objective", "objective values must be finite in [0, 1]"
            )
        parsed.append(
            _ParsedAllocation(
                record=record,
                created_at=created_at,
                objectives=(values[0], values[1], values[2]),
            )
        )
    return tuple(sorted(parsed, key=lambda item: (item.created_at, item.record.id)))


def build_feature_timeline(
    source: PredictionSourceData, config: PreprocessingConfig
) -> tuple[FeatureBucket | None, ...]:
    """Aggregate source records into a regular, privacy-preserving feature timeline."""
    if (
        not isinstance(source.slot_count, int)
        or isinstance(source.slot_count, bool)
        or source.slot_count <= 0
    ):
        raise PredictionDataError("invalid_slot_count", "slot count must be positive")

    contexts = _parse_contexts(source)
    sessions = _parse_sessions(source)
    allocations = _parse_allocations(source)
    if not contexts:
        return ()

    interval_seconds = config.interval_minutes * 60
    interval = timedelta(seconds=interval_seconds)

    contexts_by_bucket: dict[datetime, _ParsedContext] = {}
    for context in contexts:
        bucket = _floor_timestamp(context.sampled_at, interval_seconds)
        contexts_by_bucket[bucket] = context

    allocations_by_bucket: dict[datetime, list[_ParsedAllocation]] = {}
    for current_allocation in allocations:
        allocation_bucket = _floor_timestamp(current_allocation.created_at, interval_seconds)
        allocations_by_bucket.setdefault(allocation_bucket, []).append(current_allocation)

    first_bucket = min(contexts_by_bucket)
    last_bucket = max(contexts_by_bucket)
    bucket_count = int((last_bucket - first_bucket) // interval) + 1

    timeline: list[FeatureBucket | None] = []
    carried_context: _ParsedContext | None = None
    absent_intervals = 0
    previous_resolved_ratio: float | None = None
    resolved_ratios_since_gap: list[float] = []
    exit_events = tuple(
        sorted(
            (item for item in sessions if item.exited_at is not None),
            key=lambda item: (cast(datetime, item.exited_at), item.record.id),
        )
    )
    entry_index = 0
    exit_index = 0
    previously_seen_vehicles: set[int] = set()
    active_session_ids: set[int] = set()

    for offset in range(bucket_count):
        timestamp = first_bucket + offset * interval
        end = timestamp + interval
        selected_context = contexts_by_bucket.get(timestamp)
        if selected_context is not None:
            carried_context = selected_context
            absent_intervals = 0
        else:
            absent_intervals += 1

        while entry_index < len(sessions) and sessions[entry_index].entered_at < timestamp:
            previous_entry = sessions[entry_index]
            previously_seen_vehicles.add(previous_entry.record.vehicle_id)
            active_session_ids.add(previous_entry.record.id)
            entry_index += 1
        while (
            exit_index < len(exit_events)
            and cast(datetime, exit_events[exit_index].exited_at) < timestamp
        ):
            active_session_ids.discard(exit_events[exit_index].record.id)
            exit_index += 1

        bucket_entry_start = entry_index
        while entry_index < len(sessions) and sessions[entry_index].entered_at < end:
            active_session_ids.add(sessions[entry_index].record.id)
            entry_index += 1
        bucket_entries = sessions[bucket_entry_start:entry_index]
        returning_entries = sum(
            item.record.vehicle_id in previously_seen_vehicles for item in bucket_entries
        )
        previously_seen_vehicles.update(
            item.record.vehicle_id for item in bucket_entries
        )

        bucket_exit_start = exit_index
        while (
            exit_index < len(exit_events)
            and cast(datetime, exit_events[exit_index].exited_at) < end
        ):
            active_session_ids.discard(exit_events[exit_index].record.id)
            exit_index += 1
        bucket_exits = exit_events[bucket_exit_start:exit_index]

        if carried_context is None or absent_intervals > config.max_carry_intervals:
            timeline.append(None)
            previous_resolved_ratio = None
            resolved_ratios_since_gap.clear()
            continue

        occupancy_ratio = carried_context.record.occupancy_count / source.slot_count
        occupancy_change = (
            0.0
            if previous_resolved_ratio is None
            else occupancy_ratio - previous_resolved_ratio
        )
        resolved_ratios_since_gap.append(occupancy_ratio)
        mean_15m = float(np.mean(resolved_ratios_since_gap[-3:]))
        mean_60m = float(np.mean(resolved_ratios_since_gap[-12:]))

        bucket_allocations = allocations_by_bucket.get(timestamp, ())
        entry_count = len(bucket_entries)
        exit_count = len(bucket_exits)
        unique_vehicle_count = len(
            {
                *(item.record.vehicle_id for item in bucket_entries),
                *(item.record.vehicle_id for item in bucket_exits),
            }
        )
        returning_vehicle_rate = returning_entries / entry_count if entry_count else 0.0
        active_session_count = len(active_session_ids)

        allocation_count = len(bucket_allocations)
        if allocation_count:
            mean_walking_distance, mean_congestion, mean_fairness = (
                float(np.mean([item.objectives[index] for item in bucket_allocations]))
                for index in range(3)
            )
            allocation_present = 1.0
        else:
            mean_walking_distance = mean_congestion = mean_fairness = 0.0
            allocation_present = 0.0

        hour = timestamp.hour + timestamp.minute / 60
        hour_angle = 2 * math.pi * hour / 24
        weekday_angle = 2 * math.pi * timestamp.weekday() / 7
        weather = str(carried_context.record.weather).strip().lower()
        if weather not in WEATHER_CATEGORIES[:-1]:
            weather = "other"
        weather_values = tuple(float(weather == category) for category in WEATHER_CATEGORIES)

        values = (
            float(occupancy_ratio),
            float(occupancy_change),
            mean_15m,
            mean_60m,
            math.sin(hour_angle),
            math.cos(hour_angle),
            math.sin(weekday_angle),
            math.cos(weekday_angle),
            *weather_values,
            float(carried_context.record.holiday),
            float(carried_context.record.event),
            float(entry_count),
            float(exit_count),
            float(allocation_count),
            float(active_session_count),
            float(unique_vehicle_count),
            float(returning_vehicle_rate),
            mean_walking_distance,
            mean_congestion,
            mean_fairness,
            allocation_present,
        )
        if len(values) != len(FEATURE_NAMES) or not all(math.isfinite(value) for value in values):
            raise PredictionDataError(
                "invalid_feature", "feature values must match the finite feature contract"
            )
        timeline.append(FeatureBucket(timestamp=timestamp, values=values))
        previous_resolved_ratio = occupancy_ratio

    return tuple(timeline)


def _split_timeline(
    timeline: tuple[FeatureBucket | None, ...], config: PreprocessingConfig
) -> tuple[
    tuple[FeatureBucket | None, ...],
    tuple[FeatureBucket | None, ...],
    tuple[FeatureBucket | None, ...],
]:
    train_end = math.floor(len(timeline) * config.train_fraction)
    validation_end = train_end + math.floor(
        len(timeline) * config.validation_fraction
    )
    return (
        timeline[:train_end],
        timeline[train_end:validation_end],
        timeline[validation_end:],
    )


def _build_examples(
    buckets: tuple[FeatureBucket | None, ...], config: PreprocessingConfig
) -> tuple[np.ndarray, np.ndarray, tuple[datetime, ...]]:
    inputs: list[tuple[tuple[float, ...], ...]] = []
    targets: list[float] = []
    timestamps: list[datetime] = []
    target_offset = config.lookback_steps + config.horizon_steps - 1
    target_feature = FEATURE_NAMES.index("occupancy_ratio")
    for target_index in range(target_offset, len(buckets)):
        input_end = target_index - config.horizon_steps + 1
        input_start = input_end - config.lookback_steps
        window = buckets[input_start:input_end]
        target_bucket = buckets[target_index]
        if target_bucket is None or any(bucket is None for bucket in window):
            continue
        resolved_window = cast(tuple[FeatureBucket, ...], window)
        inputs.append(tuple(bucket.values for bucket in resolved_window))
        targets.append(target_bucket.values[target_feature])
        timestamps.append(target_bucket.timestamp)
    return (
        np.asarray(inputs, dtype=np.float64).reshape(
            -1, config.lookback_steps, len(FEATURE_NAMES)
        ),
        np.asarray(targets, dtype=np.float64),
        tuple(timestamps),
    )


def _partition_ended_at(
    buckets: tuple[FeatureBucket | None, ...], partition: str
) -> datetime:
    for bucket in reversed(buckets):
        if bucket is not None:
            return bucket.timestamp
    raise PredictionDataError(
        "empty_split", f"{partition} partition has no resolved boundary bucket"
    )


def _timeline_identity(timeline: tuple[FeatureBucket | None, ...]) -> tuple[object, ...]:
    """Return a privacy-safe canonical identity for shared feature values."""
    return tuple(
        None
        if bucket is None
        else (bucket.timestamp.isoformat(), tuple(float(value) for value in bucket.values))
        for bucket in timeline
    )


def build_runtime_input(source: PredictionSourceData, dataset: PreparedDataset) -> RuntimeInput:
    """Create the next-bucket input from shared aggregation and the frozen dataset scaler."""
    if not isinstance(dataset, PreparedDataset):
        raise PredictionDataError("invalid_runtime_input", "runtime requires one PreparedDataset")
    if (
        dataset.feature_names != FEATURE_NAMES
        or dataset.target_name != TARGET_NAME
        or dataset.config.interval_minutes != 5
        or dataset.config.lookback_steps != 12
        or dataset.config.horizon_steps != 1
        or dataset.slot_count != source.slot_count
    ):
        raise PredictionDataError(
            "invalid_runtime_input", "prepared dataset does not match the fixed prediction contract"
        )
    timeline = build_feature_timeline(source, dataset.config)
    latest_index = next(
        (index for index in range(len(timeline) - 1, -1, -1) if timeline[index] is not None),
        None,
    )
    if latest_index is None:
        raise PredictionDataError(
            "insufficient_history", "no resolved prediction buckets are available"
        )
    start = latest_index - dataset.config.lookback_steps + 1
    if start < 0:
        raise PredictionDataError(
            "insufficient_history", "not enough complete buckets for runtime prediction"
        )
    window = timeline[start : latest_index + 1]
    if len(window) != dataset.config.lookback_steps or any(bucket is None for bucket in window):
        raise PredictionDataError(
            "insufficient_history", "runtime history contains an unresolved bucket"
        )
    resolved = cast(tuple[FeatureBucket, ...], window)
    inputs = np.asarray([tuple(bucket.values for bucket in resolved)], dtype=np.float64)
    indices = dataset.scaler.feature_indices
    means = np.asarray(dataset.scaler.means, dtype=np.float64)
    scales = np.asarray(dataset.scaler.scales, dtype=np.float64)
    inputs[:, :, indices] = (inputs[:, :, indices] - means) / scales
    latest = resolved[-1]
    return RuntimeInput(
        inputs=inputs,
        target_at=latest.timestamp + timedelta(minutes=dataset.config.interval_minutes),
        latest_occupancy_ratio=latest.values[FEATURE_NAMES.index("occupancy_ratio")],
    )


def prepare_prediction_dataset(
    source: PredictionSourceData, config: PreprocessingConfig | None = None
) -> PreparedDataset:
    """Build deterministic, leakage-safe chronological prediction splits."""
    resolved_config = config if config is not None else PreprocessingConfig()
    timeline = build_feature_timeline(source, resolved_config)
    train_timeline, validation_timeline, test_timeline = _split_timeline(
        timeline, resolved_config
    )

    examples = tuple(
        _build_examples(partition, resolved_config)
        for partition in (train_timeline, validation_timeline, test_timeline)
    )
    for partition_name, (_, targets, _) in zip(
        ("train", "validation", "test"), examples, strict=True
    ):
        if targets.size == 0:
            raise PredictionDataError(
                "empty_split", f"{partition_name} partition contains no examples"
            )

    (train_inputs, train_targets, train_timestamps), (
        validation_inputs,
        validation_targets,
        validation_timestamps,
    ), (test_inputs, test_targets, test_timestamps) = examples
    continuous_indices = tuple(
        FEATURE_NAMES.index(name) for name in CONTINUOUS_FEATURE_NAMES
    )
    training_continuous = train_inputs[:, :, continuous_indices].reshape(
        -1, len(continuous_indices)
    )
    means = np.mean(training_continuous, axis=0)
    scales = np.std(training_continuous, axis=0, ddof=0)
    scales = np.where(scales == 0, 1.0, scales)
    for inputs in (train_inputs, validation_inputs, test_inputs):
        inputs[:, :, continuous_indices] = (
            inputs[:, :, continuous_indices] - means
        ) / scales

    if not timeline or timeline[0] is None:
        raise PredictionDataError(
            "empty_split", "source partition has no resolved starting boundary bucket"
        )
    source_started_at = timeline[0].timestamp
    source_ended_at = _partition_ended_at(timeline, "source")
    train_ended_at = _partition_ended_at(train_timeline, "train")
    validation_ended_at = _partition_ended_at(validation_timeline, "validation")

    identity = {
        "config": asdict(resolved_config),
        "feature_names": FEATURE_NAMES,
        "target_name": TARGET_NAME,
        "slot_count": source.slot_count,
        "source_started_at": source_started_at.isoformat(),
        "source_ended_at": source_ended_at.isoformat(),
        "train_ended_at": train_ended_at.isoformat(),
        "validation_ended_at": validation_ended_at.isoformat(),
        "timeline": _timeline_identity(timeline),
    }
    canonical_json = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    split_id = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    return PreparedDataset(
        feature_names=FEATURE_NAMES,
        target_name=TARGET_NAME,
        train=PreparedSplit(train_inputs, train_targets, train_timestamps),
        validation=PreparedSplit(
            validation_inputs, validation_targets, validation_timestamps
        ),
        test=PreparedSplit(test_inputs, test_targets, test_timestamps),
        scaler=ScalerMetadata(
            feature_indices=continuous_indices,
            means=tuple(float(value) for value in means),
            scales=tuple(float(value) for value in scales),
        ),
        split_id=split_id,
        source_started_at=source_started_at,
        source_ended_at=source_ended_at,
        train_ended_at=train_ended_at,
        validation_ended_at=validation_ended_at,
        config=resolved_config,
        slot_count=source.slot_count,
    )
