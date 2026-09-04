from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.config import Settings
from backend.app.db import Database
from backend.app.main import create_app
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


def make_settings(tmp_path: Path, selected_optimizer: str = "ga") -> Settings:
    config_path = tmp_path / "parking.yaml"
    write_config(config_path)
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'parking.db'}",
        parking_config_path=config_path,
        selected_optimizer=selected_optimizer,
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


def test_entry_allocates_free_slot_and_persists_atomically(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, selected_optimizer="ga")
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/vehicle/entry",
            json={"rfid_uid": "card-1", "idempotency_key": "entry-1"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["rfid_uid"] == "CARD-1"
    assert body["optimizer"] == "ga"
    assert body["gate_action"] == "open"
    assert body["slot_id"] in {1, 2, 3, 4, 5}
    with sqlite3.connect(settings.database_path) as connection:
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("vehicles", "parking_sessions", "allocations", "optimizer_runs")
        }
        occupied = connection.execute(
            "SELECT occupied FROM parking_slots WHERE id = ?", (body["slot_id"],)
        ).fetchone()[0]
    assert counts == {
        "vehicles": 1,
        "parking_sessions": 1,
        "allocations": 1,
        "optimizer_runs": 1,
    }
    assert occupied == 1


def table_counts(settings: Settings) -> dict[str, int]:
    with sqlite3.connect(settings.database_path) as connection:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("vehicles", "parking_sessions", "allocations", "optimizer_runs")
        }


def test_identical_entry_retry_replays_without_duplicate_rows(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        first = client.post(
            "/api/vehicle/entry",
            json={"rfid_uid": "CARD-1", "idempotency_key": "entry-1"},
        )
        first_counts = table_counts(settings)
        retry = client.post(
            "/api/vehicle/entry",
            json={"rfid_uid": "CARD-1", "idempotency_key": "entry-1"},
        )

    assert retry.status_code == 200
    assert retry.json() == first.json()
    assert table_counts(settings) == first_counts


def test_new_entry_for_active_vehicle_is_rejected(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        client.post(
            "/api/vehicle/entry",
            json={"rfid_uid": "CARD-1", "idempotency_key": "entry-1"},
        )
        response = client.post(
            "/api/vehicle/entry",
            json={"rfid_uid": "CARD-1", "idempotency_key": "entry-2"},
        )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "vehicle_already_parked"


def test_entry_key_reused_for_different_vehicle_is_rejected(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        client.post(
            "/api/vehicle/entry",
            json={"rfid_uid": "CARD-1", "idempotency_key": "entry-1"},
        )
        response = client.post(
            "/api/vehicle/entry",
            json={"rfid_uid": "CARD-2", "idempotency_key": "entry-1"},
        )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "idempotency_conflict"


def test_full_capacity_returns_conflict_without_partial_writes(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        with sqlite3.connect(settings.database_path) as connection:
            connection.execute("UPDATE parking_slots SET occupied = 1")
        response = client.post(
            "/api/vehicle/entry",
            json={"rfid_uid": "CARD-1", "idempotency_key": "entry-1"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "no_available_slot",
        "message": "no parking slot is available",
    }
    assert table_counts(settings) == {
        "vehicles": 0,
        "parking_sessions": 0,
        "allocations": 0,
        "optimizer_runs": 0,
    }


def test_entry_never_selects_a_preoccupied_slot(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        with sqlite3.connect(settings.database_path) as connection:
            connection.execute("UPDATE parking_slots SET occupied = 1 WHERE id = 1")
        response = client.post(
            "/api/vehicle/entry",
            json={"rfid_uid": "CARD-1", "idempotency_key": "entry-1"},
        )

    assert response.status_code == 200
    assert response.json()["slot_id"] != 1


def test_entry_persistence_failure_rolls_back_every_write(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        with sqlite3.connect(settings.database_path) as connection:
            connection.execute(
                """
                CREATE TRIGGER reject_allocation BEFORE INSERT ON allocations
                BEGIN SELECT RAISE(ABORT, 'test allocation failure'); END
                """
            )
        response = client.post(
            "/api/vehicle/entry",
            json={"rfid_uid": "CARD-1", "idempotency_key": "entry-1"},
        )

    assert response.status_code == 500
    assert table_counts(settings) == {
        "vehicles": 0,
        "parking_sessions": 0,
        "allocations": 0,
        "optimizer_runs": 0,
    }
