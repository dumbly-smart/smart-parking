"""Deterministic aggregation and feature engineering for prediction inputs."""

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import numpy as np

from prediction.models import (
    FEATURE_NAMES,
    WEATHER_CATEGORIES,
    AllocationFeatureRecord,
    ContextSampleRecord,
    FeatureBucket,
    PredictionDataError,
    PredictionSourceData,
    PreprocessingConfig,
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

    entries_by_bucket: dict[datetime, list[_ParsedSession]] = {}
    exits_by_bucket: dict[datetime, list[_ParsedSession]] = {}
    for current_session in sessions:
        entry_bucket = _floor_timestamp(current_session.entered_at, interval_seconds)
        entries_by_bucket.setdefault(entry_bucket, []).append(current_session)
        if current_session.exited_at is not None:
            exit_bucket = _floor_timestamp(current_session.exited_at, interval_seconds)
            exits_by_bucket.setdefault(exit_bucket, []).append(current_session)

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

    for offset in range(bucket_count):
        timestamp = first_bucket + offset * interval
        selected_context = contexts_by_bucket.get(timestamp)
        if selected_context is not None:
            carried_context = selected_context
            absent_intervals = 0
        else:
            absent_intervals += 1

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

        end = timestamp + interval
        bucket_entries = entries_by_bucket.get(timestamp, ())
        bucket_exits = exits_by_bucket.get(timestamp, ())
        bucket_allocations = allocations_by_bucket.get(timestamp, ())
        entry_count = len(bucket_entries)
        exit_count = len(bucket_exits)
        unique_vehicle_count = len(
            {
                *(item.record.vehicle_id for item in bucket_entries),
                *(item.record.vehicle_id for item in bucket_exits),
            }
        )
        previously_seen_vehicles = {
            item.record.vehicle_id for item in sessions if item.entered_at < timestamp
        }
        returning_entries = sum(
            item.record.vehicle_id in previously_seen_vehicles for item in bucket_entries
        )
        returning_vehicle_rate = returning_entries / entry_count if entry_count else 0.0
        active_session_count = sum(
            item.entered_at < end
            and (item.exited_at is None or item.exited_at >= end)
            for item in sessions
        )

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
