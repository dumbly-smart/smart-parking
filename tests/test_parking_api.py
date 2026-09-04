from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.config import Settings
from backend.app.db import Database
from backend.app.models.parking import VehicleOperationRequest

LEGACY_PARKING_SESSIONS_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE parking_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id INTEGER NOT NULL REFERENCES vehicles(id),
    slot_id INTEGER NOT NULL REFERENCES parking_slots(id),
    entry_idempotency_key TEXT NOT NULL UNIQUE,
    entered_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    exited_at TEXT,
    CHECK (exited_at IS NULL OR exited_at >= entered_at)
);
"""


def write_config(path: Path) -> None:
    path.write_text(
        """allocation:
  weights:
    distance: 0.35
    congestion: 0.30
    waiting: 0.20
    fairness: 0.15
slots:
  - {id: 1, name: S1, walking_distance: 0.2, zone: north}
  - {id: 2, name: S2, walking_distance: 0.3, zone: north}
  - {id: 3, name: S3, walking_distance: 0.5, zone: central}
  - {id: 4, name: S4, walking_distance: 0.7, zone: south}
  - {id: 5, name: S5, walking_distance: 0.9, zone: south}
""",
        encoding="utf-8",
    )


def make_settings(tmp_path: Path) -> Settings:
    config_path = tmp_path / "parking.yaml"
    write_config(config_path)
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'parking.db'}",
        parking_config_path=config_path,
    )


def test_vehicle_operation_request_normalizes_identifiers() -> None:
    request = VehicleOperationRequest(
        rfid_uid=" 04-a1-b2-c3 ", idempotency_key=" entry-0001 "
    )

    assert request.model_dump() == {
        "rfid_uid": "04-A1-B2-C3",
        "idempotency_key": "entry-0001",
    }


@pytest.mark.parametrize("field", ["rfid_uid", "idempotency_key"])
def test_vehicle_operation_request_rejects_blank_identifier(field: str) -> None:
    values = {"rfid_uid": "CARD-1", "idempotency_key": "entry-1"}
    values[field] = "   "

    with pytest.raises(ValidationError):
        VehicleOperationRequest.model_validate(values)


def test_initialize_migrates_exit_idempotency_column(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    database = Database(settings.database_path)
    with database.connect() as connection:
        connection.executescript(LEGACY_PARKING_SESSIONS_SCHEMA)

    database.initialize(settings.parking.slots)

    with sqlite3.connect(settings.database_path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(parking_sessions)")
        }
        indexes = {
            row[1] for row in connection.execute("PRAGMA index_list(parking_sessions)")
        }
    assert "exit_idempotency_key" in columns
    assert "unique_exit_idempotency_key" in indexes
