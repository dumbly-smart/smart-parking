from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import numpy as np
import pytest

from backend.app.config import SlotConfig
from backend.app.db import Database
from prediction.data import build_feature_timeline, prepare_prediction_dataset
from prediction.demo_data import (
    DemoDataConfig,
    DemoDataError,
    replace_prediction_demo_data,
)
from prediction.models import PreprocessingConfig

START = datetime(2026, 8, 1, tzinfo=UTC)


def initialized_database(tmp_path) -> Database:
    database = Database(tmp_path / "prediction-demo.db")
    database.initialize(
        [
            SlotConfig(id=2, name="A2", walking_distance=0.2, zone="a"),
            SlotConfig(id=9, name="B9", walking_distance=0.8, zone="b"),
            SlotConfig(id=21, name="C21", walking_distance=0.5, zone="c"),
        ]
    )
    return database


def test_regeneration_reproduces_prepared_data(tmp_path) -> None:
    database = initialized_database(tmp_path)
    config = DemoDataConfig(dataset_key="demo", seed=11, start_at=START, days=7)

    replace_prediction_demo_data(database, config)
    first = prepare_prediction_dataset(database.load_prediction_source_data())
    replace_prediction_demo_data(database, config)
    second = prepare_prediction_dataset(database.load_prediction_source_data())

    np.testing.assert_array_equal(first.train.inputs, second.train.inputs)
    np.testing.assert_array_equal(first.validation.inputs, second.validation.inputs)
    np.testing.assert_array_equal(first.test.inputs, second.test.inputs)
    assert first.split_id == second.split_id


def test_replacement_preserves_unowned_rows_and_does_not_accumulate(tmp_path) -> None:
    database = initialized_database(tmp_path)
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO context_samples (occupancy_count, weather, holiday, event, sampled_at)
            VALUES (1, 'clear', 0, 0, '2026-07-31T23:55:00Z')
            """
        )

    config = DemoDataConfig(dataset_key="demo", seed=11, start_at=START, days=7)
    first = replace_prediction_demo_data(database, config)
    second = replace_prediction_demo_data(database, config)

    assert first == second
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM context_samples").fetchone()[0] == (
            first.context_samples + 1
        )
        assert (
            connection.execute(
                "SELECT occupancy_count FROM context_samples WHERE sampled_at = ?",
                ("2026-07-31T23:55:00Z",),
            ).fetchone()[0]
            == 1
        )


def test_seed_changes_generated_values_and_all_feature_families_are_present(tmp_path) -> None:
    database = initialized_database(tmp_path)
    first = replace_prediction_demo_data(
        database, DemoDataConfig(dataset_key="demo", seed=11, start_at=START, days=7)
    )
    first_source = database.load_prediction_source_data()
    replace_prediction_demo_data(
        database, DemoDataConfig(dataset_key="demo", seed=12, start_at=START, days=7)
    )
    second_source = database.load_prediction_source_data()

    assert first.context_samples == 7 * 24 * 12
    assert [item.occupancy_count for item in first_source.context_samples] != [
        item.occupancy_count for item in second_source.context_samples
    ]
    timeline = build_feature_timeline(first_source, PreprocessingConfig())
    values = [bucket.values for bucket in timeline if bucket is not None]
    assert any(value[11] == 1.0 for value in values)  # a weather one-hot feature
    assert all(any(value[index] == 1.0 for value in values) for index in range(8, 15))
    assert any(value[15] == 1.0 for value in values)
    assert any(value[16] == 1.0 for value in values)
    assert any(value[17] > 0.0 for value in values)
    assert any(value[20] > 0.0 for value in values)
    assert any(value[26] == 1.0 for value in values)


def test_generated_context_occupancy_matches_sessions_and_slot_state(tmp_path) -> None:
    database = initialized_database(tmp_path)
    summary = replace_prediction_demo_data(
        database, DemoDataConfig(dataset_key="demo", seed=11, start_at=START, days=7)
    )

    with database.connect() as connection:
        samples = connection.execute(
            "SELECT occupancy_count, sampled_at FROM context_samples ORDER BY sampled_at"
        ).fetchall()
        for sample in samples:
            active = connection.execute(
                """SELECT COUNT(*) FROM parking_sessions
                   WHERE entered_at <= ? AND (exited_at IS NULL OR exited_at > ?)""",
                (sample["sampled_at"], sample["sampled_at"]),
            ).fetchone()[0]
            assert active == sample["occupancy_count"]
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM context_samples WHERE occupancy_count > 3"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM allocations").fetchone()[0]
            == summary.allocations
        )
        assert connection.execute("SELECT COUNT(*) FROM optimizer_runs").fetchone()[0] == (
            summary.optimizer_runs
        )
        active_slots = connection.execute(
            "SELECT COUNT(*) FROM parking_slots WHERE occupied = 1"
        ).fetchone()[0]
        active_sessions = connection.execute(
            "SELECT COUNT(*) FROM parking_sessions WHERE exited_at IS NULL"
        ).fetchone()[0]
        assert active_slots == active_sessions


def test_seeder_rejects_unowned_occupied_slot_without_modifying_it(tmp_path) -> None:
    database = initialized_database(tmp_path)
    with database.connect() as connection:
        connection.execute("UPDATE parking_slots SET occupied = 1 WHERE id = 2")

    with pytest.raises(DemoDataError) as raised:
        replace_prediction_demo_data(
            database, DemoDataConfig(dataset_key="review", seed=11, start_at=START, days=1)
        )

    assert raised.value.code == "occupied_demo_database"
    with database.connect() as connection:
        assert (
            connection.execute("SELECT occupied FROM parking_slots WHERE id = 2").fetchone()[0] == 1
        )
        assert connection.execute("SELECT COUNT(*) FROM context_samples").fetchone()[0] == 0


def test_failed_replacement_rolls_back_previous_complete_dataset(tmp_path) -> None:
    database = initialized_database(tmp_path)
    config = DemoDataConfig(dataset_key="demo", seed=11, start_at=START, days=7)
    replace_prediction_demo_data(database, config)
    before = database.load_prediction_source_data()
    with database.connect() as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_demo_allocation BEFORE INSERT ON allocations
            BEGIN SELECT RAISE(ABORT, 'injected failure'); END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="injected failure"):
        replace_prediction_demo_data(database, config)

    assert database.load_prediction_source_data() == before


@pytest.mark.parametrize(
    "overrides",
    [
        {"dataset_key": ""},
        {"dataset_key": "bad key"},
        {"seed": True},
        {"start_at": datetime(2026, 8, 1, 0, 1, tzinfo=UTC)},
        {"start_at": datetime(2026, 8, 1)},
        {"days": 0},
        {"days": True},
    ],
)
def test_invalid_demo_config_has_stable_typed_error(overrides: dict[str, object]) -> None:
    with pytest.raises(DemoDataError) as raised:
        DemoDataConfig(**overrides)

    assert raised.value.code == "invalid_demo_config"
