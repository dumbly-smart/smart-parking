import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from backend.app.config import SlotConfig
from backend.app.db import Database
from prediction.data import build_feature_timeline, parse_utc_timestamp
from prediction.models import (
    CONTINUOUS_FEATURE_NAMES,
    FEATURE_NAMES,
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


def session(
    record_id: int,
    *,
    vehicle_id: int,
    entered_at: str,
    exited_at: str | None = None,
) -> SessionRecord:
    return SessionRecord(record_id, vehicle_id, entered_at, exited_at)


def allocation(
    record_id: int,
    *,
    vehicle_id: int,
    created_at: str,
    distance: float = 0.0,
    congestion: float = 0.0,
    fairness: float = 0.0,
) -> AllocationFeatureRecord:
    return AllocationFeatureRecord(
        record_id,
        vehicle_id,
        created_at,
        json.dumps(
            {"distance": distance, "congestion": congestion, "fairness": fairness}
        ),
    )


def prediction_source(
    *,
    slot_count: int = 5,
    context_counts: list[int] | tuple[int, ...] = (0,) * 13,
    weather: str = "clear",
    holiday: int = 0,
    event: int = 0,
    sessions: tuple[SessionRecord, ...] = (),
    allocations: tuple[AllocationFeatureRecord, ...] = (),
) -> PredictionSourceData:
    return PredictionSourceData(
        slot_count=slot_count,
        context_samples=tuple(
            ContextSampleRecord(
                id=index + 1,
                occupancy_count=count,
                weather=weather,
                holiday=holiday,
                event=event,
                sampled_at=(
                    datetime(2026, 9, 4, 10, tzinfo=UTC) + timedelta(minutes=index * 5)
                ).isoformat(),
            )
            for index, count in enumerate(context_counts)
        ),
        sessions=sessions,
        allocations=allocations,
    )


def source_with_context_minutes(
    minutes: tuple[int, ...], *, slot_count: int
) -> PredictionSourceData:
    return PredictionSourceData(
        slot_count=slot_count,
        context_samples=tuple(
            ContextSampleRecord(
                id=index + 1,
                occupancy_count=index,
                weather="clear",
                holiday=0,
                event=0,
                sampled_at=f"2026-09-04T10:{minute:02d}:00Z",
            )
            for index, minute in enumerate(minutes)
        ),
        sessions=(),
        allocations=(),
    )


def feature(bucket: FeatureBucket, name: str) -> float:
    return bucket.values[FEATURE_NAMES.index(name)]


def initialized_prediction_database(tmp_path: Path, slot_ids: tuple[int, ...]) -> Database:
    database = Database(tmp_path / "prediction.db")
    database.initialize(
        [
            SlotConfig(
                id=slot_id,
                name=f"S{slot_id}",
                walking_distance=0.5,
                zone="prediction",
            )
            for slot_id in slot_ids
        ]
    )
    return database


def insert_lifecycle_allocation(
    connection: sqlite3.Connection,
    *,
    rfid_uid: str,
    entered_at: str,
    distance: float,
    congestion: float,
    fairness: float,
) -> tuple[int, int, int, int]:
    vehicle_cursor = connection.execute(
        "INSERT INTO vehicles (rfid_uid, created_at) VALUES (?, ?)",
        (rfid_uid, entered_at),
    )
    vehicle_id = int(vehicle_cursor.lastrowid)
    session_cursor = connection.execute(
        """
        INSERT INTO parking_sessions (
            vehicle_id, slot_id, entry_idempotency_key, entry_slot_name, entered_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (vehicle_id, 2, "prediction-entry", "S2", entered_at),
    )
    session_id = int(session_cursor.lastrowid)
    objective_cursor = connection.execute(
        """
        INSERT INTO optimizer_runs (
            algorithm, scenario_id, chosen_slot_id, best_cost, iterations,
            runtime_ms, objective_breakdown, seed, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "test",
            "prediction-source",
            2,
            1.5,
            1,
            1.0,
            json.dumps(
                {"distance": distance, "congestion": congestion, "fairness": fairness}
            ),
            "0x0",
            entered_at,
        ),
    )
    optimizer_run_id = int(objective_cursor.lastrowid)
    allocation_cursor = connection.execute(
        """
        INSERT INTO allocations (
            session_id, optimizer_run_id, slot_id, idempotency_key, created_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (session_id, optimizer_run_id, 2, "prediction-allocation", entered_at),
    )
    allocation_id = int(allocation_cursor.lastrowid)
    return vehicle_id, session_id, optimizer_run_id, allocation_id


def test_database_loads_ordered_prediction_sources_without_rfid(tmp_path: Path) -> None:
    database = initialized_prediction_database(tmp_path, slot_ids=(2, 9))
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO context_samples "
            "(occupancy_count, weather, holiday, event, sampled_at) "
            "VALUES (1, 'rain', 0, 1, '2026-09-04T10:05:00Z')"
        )
        connection.execute(
            "INSERT INTO context_samples "
            "(occupancy_count, weather, holiday, event, sampled_at) "
            "VALUES (0, 'clear', 0, 0, '2026-09-04T10:00:00Z')"
        )
        insert_lifecycle_allocation(
            connection,
            rfid_uid="private-tag",
            entered_at="2026-09-04T10:02:00Z",
            distance=0.25,
            congestion=0.5,
            fairness=0.75,
        )

    source = database.load_prediction_source_data()

    assert source.slot_count == 2
    assert [row.sampled_at for row in source.context_samples] == [
        "2026-09-04T10:00:00Z",
        "2026-09-04T10:05:00Z",
    ]
    assert source.sessions[0].vehicle_id == source.allocations[0].vehicle_id
    assert "private-tag" not in repr(source)


def test_feature_timeline_aggregates_context_sessions_and_allocations() -> None:
    source = prediction_source(
        slot_count=4,
        context_counts=[0, 1, 2, 2, 3, 3, 2, 2, 1, 1, 2, 3, 4],
        weather="rain",
        holiday=1,
        event=1,
        sessions=(
            session(1, vehicle_id=7, entered_at="2026-09-04T10:01:00Z"),
            session(2, vehicle_id=7, entered_at="2026-09-04T10:06:00Z"),
        ),
        allocations=(
            allocation(
                1,
                vehicle_id=7,
                created_at="2026-09-04T10:02:00Z",
                distance=0.25,
                congestion=0.5,
                fairness=0.75,
            ),
        ),
    )

    timeline = build_feature_timeline(source, PreprocessingConfig())
    first = timeline[0]

    assert len(timeline) == 13
    assert first is not None
    assert feature(first, "occupancy_ratio") == 0
    assert feature(first, "entry_count") == 1
    assert feature(first, "active_session_count") == 1
    assert feature(first, "unique_vehicle_count") == 1
    assert feature(first, "allocation_count") == 1
    assert feature(first, "mean_walking_distance") == 0.25
    assert feature(first, "mean_congestion") == 0.5
    assert feature(first, "mean_fairness") == 0.75
    assert feature(first, "allocation_present") == 1
    assert feature(first, "weather_rain") == 1
    assert feature(first, "holiday") == 1
    assert feature(first, "event") == 1
    assert all(np.isfinite(first.values))

    second = timeline[1]
    assert second is not None
    assert feature(second, "occupancy_change") == 0.25
    assert feature(second, "occupancy_mean_15m") == 0.125
    assert feature(second, "entry_count") == 1
    assert feature(second, "returning_vehicle_rate") == 1
    assert feature(second, "allocation_present") == 0


def test_feature_timeline_carries_short_gaps_and_preserves_long_gaps() -> None:
    source = source_with_context_minutes((0, 20, 25, 30), slot_count=5)

    timeline = build_feature_timeline(source, PreprocessingConfig())

    assert [bucket is None for bucket in timeline[:7]] == [
        False,
        False,
        False,
        False,
        False,
        False,
        False,
    ]
    source = source_with_context_minutes((0, 25, 30), slot_count=5)
    timeline = build_feature_timeline(source, PreprocessingConfig())
    assert timeline[4] is None

    following = timeline[5]
    assert following is not None
    assert feature(following, "occupancy_change") == 0
    assert feature(following, "occupancy_mean_60m") == 0.2


def test_feature_timeline_sorts_and_selects_latest_context_in_bucket() -> None:
    source = PredictionSourceData(
        slot_count=5,
        context_samples=(
            ContextSampleRecord(8, 4, "hail", 1, 0, "2026-09-04T10:01:00Z"),
            ContextSampleRecord(3, 1, "rain", 0, 1, "2026-09-04T10:04:00Z"),
            ContextSampleRecord(9, 2, " Cloudy ", 1, 1, "2026-09-04T10:04:00Z"),
        ),
        sessions=(),
        allocations=(),
    )

    timeline = build_feature_timeline(source, PreprocessingConfig())

    assert len(timeline) == 1
    bucket = timeline[0]
    assert bucket is not None
    assert feature(bucket, "occupancy_ratio") == 0.4
    assert feature(bucket, "weather_cloudy") == 1
    assert feature(bucket, "holiday") == 1
    assert feature(bucket, "event") == 1


def test_feature_timeline_uses_half_open_session_boundaries() -> None:
    source = prediction_source(
        sessions=(
            session(
                2,
                vehicle_id=7,
                entered_at="2026-09-04T10:06:00Z",
                exited_at="2026-09-04T10:10:00Z",
            ),
            session(
                1,
                vehicle_id=7,
                entered_at="2026-09-04T10:01:00Z",
                exited_at="2026-09-04T10:05:00Z",
            ),
        )
    )

    timeline = build_feature_timeline(source, PreprocessingConfig())
    first, second, third = timeline[:3]

    assert first is not None and second is not None and third is not None
    assert feature(first, "active_session_count") == 1
    assert feature(second, "entry_count") == 1
    assert feature(second, "exit_count") == 1
    assert feature(second, "unique_vehicle_count") == 1
    assert feature(second, "returning_vehicle_rate") == 1
    assert feature(second, "active_session_count") == 1
    assert feature(third, "exit_count") == 1
    assert feature(third, "active_session_count") == 0


@pytest.mark.parametrize("value", ["2026-09-04T10:00:00", "not-a-timestamp"])
def test_parse_utc_timestamp_rejects_invalid_timestamps(value: str) -> None:
    with pytest.raises(PredictionDataError) as raised:
        parse_utc_timestamp(value, "sampled_at")

    assert raised.value.code == "invalid_timestamp"


@pytest.mark.parametrize(
    ("source", "code"),
    [
        (replace(prediction_source(), slot_count=0), "invalid_slot_count"),
        (
            replace(
                prediction_source(),
                context_samples=(
                    ContextSampleRecord(1, 6, "clear", 0, 0, "2026-09-04T10:00:00Z"),
                ),
            ),
            "invalid_occupancy",
        ),
        (
            replace(
                prediction_source(),
                context_samples=(
                    ContextSampleRecord(1, 0, "clear", 2, 0, "2026-09-04T10:00:00Z"),
                ),
            ),
            "invalid_flag",
        ),
        (
            replace(
                prediction_source(),
                allocations=(
                    AllocationFeatureRecord(1, 7, "2026-09-04T10:00:00Z", "not-json"),
                ),
            ),
            "invalid_objective",
        ),
        (
            replace(
                prediction_source(),
                allocations=(
                    allocation(
                        1,
                        vehicle_id=7,
                        created_at="2026-09-04T10:00:00Z",
                        distance=float("nan"),
                    ),
                ),
            ),
            "invalid_objective",
        ),
        (
            replace(
                prediction_source(),
                sessions=(
                    session(
                        1,
                        vehicle_id=7,
                        entered_at="2026-09-04T10:05:00Z",
                        exited_at="2026-09-04T10:04:59Z",
                    ),
                ),
            ),
            "invalid_session",
        ),
    ],
)
def test_feature_timeline_rejects_invalid_source_data(
    source: PredictionSourceData, code: str
) -> None:
    with pytest.raises(PredictionDataError) as raised:
        build_feature_timeline(source, PreprocessingConfig())

    assert raised.value.code == code


def test_feature_timeline_rejects_duplicate_record_ids() -> None:
    duplicate = ContextSampleRecord(1, 0, "clear", 0, 0, "2026-09-04T10:05:00Z")
    source = replace(
        prediction_source(context_counts=(0,)),
        context_samples=(
            ContextSampleRecord(1, 0, "clear", 0, 0, "2026-09-04T10:00:00Z"),
            duplicate,
        ),
    )

    with pytest.raises(PredictionDataError) as raised:
        build_feature_timeline(source, PreprocessingConfig())

    assert raised.value.code == "duplicate_id"


def test_preprocessing_config_has_approved_defaults() -> None:
    config = PreprocessingConfig()

    assert config.interval_minutes == 5
    assert config.lookback_steps == 12
    assert config.horizon_steps == 1
    assert config.train_fraction == 0.70
    assert config.validation_fraction == 0.15
    assert config.max_carry_intervals == 3


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"interval_minutes": 0}, "invalid_config"),
        ({"interval_minutes": 10}, "invalid_config"),
        ({"lookback_steps": 0}, "invalid_config"),
        ({"lookback_steps": 4}, "invalid_config"),
        ({"horizon_steps": 0}, "invalid_config"),
        ({"horizon_steps": 3}, "invalid_config"),
        ({"train_fraction": 0.9, "validation_fraction": 0.2}, "invalid_config"),
        ({"max_carry_intervals": -1}, "invalid_config"),
    ],
)
def test_preprocessing_config_rejects_invalid_values(
    overrides: dict[str, object], code: str
) -> None:
    with pytest.raises(PredictionDataError) as raised:
        PreprocessingConfig(**overrides)

    assert raised.value.code == code


def test_prepared_split_copies_and_freezes_arrays() -> None:
    source_inputs = np.zeros((2, 12, len(FEATURE_NAMES)), dtype=np.float64)
    source_targets = np.array([0.2, 0.4], dtype=np.float64)
    split = PreparedSplit(
        inputs=source_inputs,
        targets=source_targets,
        target_timestamps=(
            datetime(2026, 9, 4, 10, tzinfo=UTC),
            datetime(2026, 9, 4, 10, 5, tzinfo=UTC),
        ),
    )
    source_inputs[0, 0, 0] = 99

    assert split.inputs[0, 0, 0] == 0
    assert not split.inputs.flags.writeable
    assert not split.targets.flags.writeable
    with pytest.raises(ValueError):
        split.inputs[0, 0, 0] = 1


def _prepared_dataset(
    *,
    train_timestamps: tuple[datetime, ...] = (datetime(2026, 9, 4, 10, tzinfo=UTC),),
    validation_timestamps: tuple[datetime, ...] = (datetime(2026, 9, 4, 11, tzinfo=UTC),),
    test_timestamps: tuple[datetime, ...] = (datetime(2026, 9, 4, 12, tzinfo=UTC),),
    scaler_indices: tuple[int, ...] | None = None,
) -> PreparedDataset:
    values = np.zeros((1, 12, len(FEATURE_NAMES)), dtype=np.float64)

    def split(timestamps: tuple[datetime, ...]) -> PreparedSplit:
        return PreparedSplit(values, np.zeros(1), timestamps)

    indices = (
        tuple(FEATURE_NAMES.index(name) for name in CONTINUOUS_FEATURE_NAMES)
        if scaler_indices is None
        else scaler_indices
    )
    return PreparedDataset(
        feature_names=FEATURE_NAMES,
        target_name="occupancy_ratio",
        train=split(train_timestamps),
        validation=split(validation_timestamps),
        test=split(test_timestamps),
        scaler=ScalerMetadata(indices, tuple(0.0 for _ in indices), tuple(1.0 for _ in indices)),
        split_id="split",
        source_started_at=datetime(2026, 9, 4, 9, tzinfo=UTC),
        source_ended_at=datetime(2026, 9, 4, 13, tzinfo=UTC),
        train_ended_at=datetime(2026, 9, 4, 10, 30, tzinfo=UTC),
        validation_ended_at=datetime(2026, 9, 4, 11, 30, tzinfo=UTC),
        config=PreprocessingConfig(),
        slot_count=10,
    )


@pytest.mark.parametrize(
    ("train_timestamps", "validation_timestamps", "test_timestamps"),
    [
        (
            (datetime(2026, 9, 4, 11, tzinfo=UTC),),
            (datetime(2026, 9, 4, 10, tzinfo=UTC),),
            (datetime(2026, 9, 4, 12, tzinfo=UTC),),
        ),
        (
            (datetime(2026, 9, 4, 10, 45, tzinfo=UTC),),
            (datetime(2026, 9, 4, 11, tzinfo=UTC),),
            (datetime(2026, 9, 4, 12, tzinfo=UTC),),
        ),
        (
            (datetime(2026, 9, 4, 10, tzinfo=UTC),),
            (datetime(2026, 9, 4, 11, tzinfo=UTC),),
            (datetime(2026, 9, 4, 14, tzinfo=UTC),),
        ),
    ],
)
def test_prepared_dataset_rejects_overlapping_or_out_of_bound_timestamps(
    train_timestamps: tuple[datetime, ...],
    validation_timestamps: tuple[datetime, ...],
    test_timestamps: tuple[datetime, ...],
) -> None:
    with pytest.raises(PredictionDataError) as raised:
        _prepared_dataset(
            train_timestamps=train_timestamps,
            validation_timestamps=validation_timestamps,
            test_timestamps=test_timestamps,
        )

    assert raised.value.code == "invalid_dataset"


@pytest.mark.parametrize(
    "scaler_indices",
    [
        (0,),
        tuple(FEATURE_NAMES.index(name) for name in CONTINUOUS_FEATURE_NAMES[:-1]),
        (
            *tuple(FEATURE_NAMES.index(name) for name in CONTINUOUS_FEATURE_NAMES),
            FEATURE_NAMES.index("holiday"),
        ),
    ],
)
def test_prepared_dataset_requires_exact_continuous_scaler_features(
    scaler_indices: tuple[int, ...],
) -> None:
    with pytest.raises(PredictionDataError) as raised:
        _prepared_dataset(scaler_indices=scaler_indices)

    assert raised.value.code == "invalid_dataset"
