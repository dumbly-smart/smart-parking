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
CREATE TABLE vehicles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rfid_uid TEXT NOT NULL UNIQUE
);
CREATE TABLE parking_slots (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    walking_distance REAL NOT NULL,
    zone TEXT NOT NULL,
    occupied INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE TABLE parking_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id INTEGER NOT NULL REFERENCES vehicles(id),
    slot_id INTEGER NOT NULL REFERENCES parking_slots(id),
    entry_idempotency_key TEXT NOT NULL UNIQUE,
    entered_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    exited_at TEXT
);
"""


def write_config(path: Path) -> None:
    path.write_text(
        """allocation:
  weights: {distance: 0.35, congestion: 0.30, waiting: 0.20, fairness: 0.15}
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


def table_counts(path: Path) -> dict[str, int]:
    with sqlite3.connect(path) as connection:
        return {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("vehicles", "parking_sessions", "allocations", "optimizer_runs")
        }


def post_entry(client: TestClient, uid: str = "card-1", key: str = "entry-1"):
    return client.post(
        "/api/vehicle/entry", json={"rfid_uid": uid, "idempotency_key": key}
    )


def post_exit(client: TestClient, uid: str = "card-1", key: str = "exit-1"):
    return client.post(
        "/api/vehicle/exit", json={"rfid_uid": uid, "idempotency_key": key}
    )


def test_entry_allocates_free_slot_and_persists_atomically(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, selected_optimizer="ga")
    with TestClient(create_app(settings)) as client:
        response = post_entry(client)

    assert response.status_code == 200
    body = response.json()
    assert body["rfid_uid"] == "CARD-1"
    assert body["optimizer"] == "ga"
    assert body["gate_action"] == "open"
    assert body["slot_id"] in {1, 2, 3, 4, 5}
    assert table_counts(settings.database_path) == {
        "vehicles": 1,
        "parking_sessions": 1,
        "allocations": 1,
        "optimizer_runs": 1,
    }
    with sqlite3.connect(settings.database_path) as connection:
        occupied = connection.execute(
            "SELECT occupied FROM parking_slots WHERE id = ?", (body["slot_id"],)
        ).fetchone()[0]
    assert occupied == 1


def test_entry_retry_replays_without_duplicate_rows(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    payload = {"rfid_uid": "card-1", "idempotency_key": "entry-1"}
    with TestClient(create_app(settings)) as client:
        first = client.post("/api/vehicle/entry", json=payload)
        retry = client.post("/api/vehicle/entry", json=payload)

    assert retry.status_code == 200
    assert retry.json() == first.json()
    assert table_counts(settings.database_path) == {
        "vehicles": 1,
        "parking_sessions": 1,
        "allocations": 1,
        "optimizer_runs": 1,
    }


def test_new_entry_key_for_active_vehicle_is_rejected(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        assert post_entry(client).status_code == 200
        response = post_entry(client, key="entry-2")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "vehicle_already_parked"
    assert table_counts(settings.database_path)["parking_sessions"] == 1


def test_entry_never_assigns_preoccupied_slots(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    database = Database(settings.database_path)
    database.initialize(settings.parking.slots)
    with database.connect() as connection:
        connection.execute("UPDATE parking_slots SET occupied = 1 WHERE id < 5")

    with TestClient(create_app(settings)) as client:
        response = post_entry(client)

    assert response.status_code == 200
    assert response.json()["slot_id"] == 5


def test_full_capacity_rolls_back_every_entry_write(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    database = Database(settings.database_path)
    database.initialize(settings.parking.slots)
    with database.connect() as connection:
        connection.execute("UPDATE parking_slots SET occupied = 1")

    with TestClient(create_app(settings)) as client:
        response = post_entry(client)

    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "code": "no_available_slot",
            "message": "no parking slot is available",
        }
    }
    assert table_counts(settings.database_path) == {
        "vehicles": 0,
        "parking_sessions": 0,
        "allocations": 0,
        "optimizer_runs": 0,
    }


def test_entry_transaction_rolls_back_when_allocation_insert_fails(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    database = Database(settings.database_path)
    database.initialize(settings.parking.slots)
    with database.connect() as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_allocation BEFORE INSERT ON allocations
            BEGIN SELECT RAISE(ABORT, 'test allocation failure'); END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="test allocation failure"):
        with TestClient(create_app(settings), raise_server_exceptions=True) as client:
            post_entry(client)

    assert table_counts(settings.database_path) == {
        "vehicles": 0,
        "parking_sessions": 0,
        "allocations": 0,
        "optimizer_runs": 0,
    }


def test_exit_closes_session_and_frees_slot(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        entry = post_entry(client).json()
        response = post_exit(client)

    assert response.status_code == 200
    assert response.json()["gate_action"] == "open"
    assert response.json()["slot_id"] == entry["slot_id"]
    with sqlite3.connect(settings.database_path) as connection:
        session = connection.execute(
            "SELECT exited_at, exit_idempotency_key FROM parking_sessions"
        ).fetchone()
        occupied = connection.execute(
            "SELECT occupied FROM parking_slots WHERE id = ?", (entry["slot_id"],)
        ).fetchone()[0]
    assert session[0] is not None
    assert session[1] == "exit-1"
    assert occupied == 0


def test_exit_retry_replays_original_result(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        post_entry(client)
        first = post_exit(client)
        retry = post_exit(client)

    assert retry.status_code == 200
    assert retry.json() == first.json()
    assert table_counts(settings.database_path)["parking_sessions"] == 1


@pytest.mark.parametrize("uid", ["unknown-card", "card-1"])
def test_exit_without_active_session_is_rejected(tmp_path: Path, uid: str) -> None:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        if uid == "card-1":
            post_entry(client)
            post_exit(client)
        response = post_exit(client, uid=uid, key="another-exit")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "vehicle_not_parked"


@pytest.mark.parametrize("first_operation", ["entry", "exit"])
def test_idempotency_key_cannot_cross_operation_namespaces(
    tmp_path: Path, first_operation: str
) -> None:
    settings = make_settings(tmp_path)
    shared_key = "shared-operation-key"
    with TestClient(create_app(settings)) as client:
        if first_operation == "entry":
            assert post_entry(client, key=shared_key).status_code == 200
            response = post_exit(client, key=shared_key)
        else:
            assert post_entry(client).status_code == 200
            assert post_exit(client, key=shared_key).status_code == 200
            response = post_entry(client, key=shared_key)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "idempotency_conflict"


def test_entry_key_cannot_be_reused_for_another_vehicle(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        assert post_entry(client, uid="card-1", key="shared-key").status_code == 200
        response = post_entry(client, uid="card-2", key="shared-key")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "idempotency_conflict"
    assert table_counts(settings.database_path)["vehicles"] == 1
