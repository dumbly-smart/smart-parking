from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.config import Settings
from backend.app.db import Database
from backend.app.main import create_app

EXPECTED_TABLES = {
    "allocations",
    "context_samples",
    "occupancy_events",
    "optimizer_runs",
    "parking_sessions",
    "parking_slots",
    "prediction_runs",
    "vehicles",
}

LEGACY_SLOT_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE parking_slots (
    id INTEGER PRIMARY KEY CHECK (id BETWEEN 1 AND 5),
    name TEXT NOT NULL UNIQUE,
    walking_distance REAL NOT NULL CHECK (walking_distance BETWEEN 0 AND 1),
    zone TEXT NOT NULL,
    occupied INTEGER NOT NULL DEFAULT 0 CHECK (occupied IN (0, 1)),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE occupancy_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slot_id INTEGER NOT NULL REFERENCES parking_slots(id),
    occupied INTEGER NOT NULL CHECK (occupied IN (0, 1)),
    confidence REAL CHECK (confidence BETWEEN 0 AND 1),
    source TEXT NOT NULL,
    observed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
"""


def write_config(
    path: Path, slot_ids: list[int] | None = None, distance_weight: float = 0.35
) -> None:
    slot_ids = [1, 2, 3, 4, 5] if slot_ids is None else slot_ids
    slots = "\n".join(
        f'  - id: {slot_id}\n    name: "S{slot_id}"\n'
        f'    walking_distance: 0.5\n    zone: "zone-{slot_id}"'
        for slot_id in slot_ids
    )
    path.write_text(
        "allocation:\n"
        f"  weights:\n    distance: {distance_weight}\n    congestion: 0.30\n"
        "    waiting: 0.20\n    fairness: 0.15\n"
        f"slots:\n{slots}\n",
        encoding="utf-8",
    )


def make_settings(tmp_path: Path) -> Settings:
    return make_settings_for_ids(tmp_path, [1, 2, 3, 4, 5])


def make_settings_for_ids(tmp_path: Path, slot_ids: list[int]) -> Settings:
    config_path = tmp_path / "parking.yaml"
    write_config(config_path, slot_ids)
    return Settings(
        mode="demo",
        database_url=f"sqlite:///{tmp_path / 'parking.db'}",
        parking_config_path=config_path,
    )


@pytest.mark.parametrize("slot_ids", [[7], [2, 4, 9, 12, 20, 31]])
def test_settings_accepts_non_empty_unique_positive_slot_ids(
    tmp_path: Path, slot_ids: list[int]
) -> None:
    settings = make_settings_for_ids(tmp_path, slot_ids)

    assert [slot.id for slot in settings.parking.slots] == slot_ids
    assert settings.parking.allocation.weights.model_dump() == {
        "distance": 0.35,
        "congestion": 0.30,
        "waiting": 0.20,
        "fairness": 0.15,
    }


@pytest.mark.parametrize("slot_ids", [[], [1, 1], [0]])
def test_settings_rejects_empty_duplicate_or_non_positive_slot_ids(
    tmp_path: Path, slot_ids: list[int]
) -> None:
    config_path = tmp_path / "invalid.yaml"
    write_config(config_path, slot_ids)

    with pytest.raises((ValueError, ValidationError)):
        Settings(parking_config_path=config_path)


def test_settings_rejects_invalid_allocation_weights(tmp_path: Path) -> None:
    config_path = tmp_path / "invalid.yaml"
    write_config(config_path, distance_weight=0.40)

    with pytest.raises((ValueError, ValidationError)):
        Settings(parking_config_path=config_path)


def test_database_dynamic_initialization_is_idempotent_and_creates_planned_tables(
    tmp_path: Path,
) -> None:
    settings = make_settings_for_ids(tmp_path, [8, 2, 21])
    database = Database(settings.database_path)

    database.initialize(settings.parking.slots)
    database.initialize(settings.parking.slots)

    with sqlite3.connect(settings.database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
            if not row[0].startswith("sqlite_")
        }
        slots = connection.execute(
            "SELECT id, name, occupied FROM parking_slots ORDER BY id"
        ).fetchall()

    assert tables == EXPECTED_TABLES
    assert slots == [(2, "S2", 0), (8, "S8", 0), (21, "S21", 0)]


def test_database_migrates_legacy_slot_constraint_without_losing_references(
    tmp_path: Path,
) -> None:
    settings = make_settings_for_ids(tmp_path, [1, 2, 3, 4, 5, 8])
    database = Database(settings.database_path)
    with database.connect() as connection:
        connection.executescript(LEGACY_SLOT_SCHEMA)
        connection.executemany(
            """
            INSERT INTO parking_slots (id, name, walking_distance, zone)
            VALUES (?, ?, ?, ?)
            """,
            [(slot_id, f"S{slot_id}", 0.5, f"zone-{slot_id}") for slot_id in range(1, 6)],
        )
        connection.execute(
            """
            INSERT INTO occupancy_events (slot_id, occupied, confidence, source)
            VALUES (1, 1, 0.95, 'legacy-camera')
            """
        )

    database.initialize(settings.parking.slots)

    with sqlite3.connect(settings.database_path) as connection:
        sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'parking_slots'"
        ).fetchone()[0]
        event = connection.execute(
            "SELECT slot_id, occupied FROM occupancy_events"
        ).fetchone()
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
    assert "BETWEEN 1 AND 5" not in sql
    assert event == (1, 1)
    assert foreign_key_errors == []
    assert database.slot_count() == 6


def test_database_dynamic_reinitialization_rejects_unconfigured_persisted_slot(
    tmp_path: Path,
) -> None:
    settings = make_settings_for_ids(tmp_path, [2, 8, 21])
    database = Database(settings.database_path)
    database.initialize(settings.parking.slots)

    with pytest.raises(ValueError, match="persisted parking slot"):
        database.initialize(settings.parking.slots[:2])


def test_database_dynamic_initialization_rejects_empty_configuration(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "parking.db")

    with pytest.raises(ValueError, match="at least one parking slot"):
        database.initialize([])


def test_health_reports_database_and_configured_slot_count(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)

    with TestClient(create_app(settings)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "mode": "demo",
        "database": "ok",
        "slot_count": 5,
    }


def test_health_is_degraded_when_database_slot_count_differs_from_configuration(
    tmp_path: Path,
) -> None:
    settings = make_settings(tmp_path)

    with TestClient(create_app(settings)) as client:
        with sqlite3.connect(settings.database_path) as connection:
            connection.execute("DELETE FROM parking_slots WHERE id = 5")
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["slot_count"] == 4
