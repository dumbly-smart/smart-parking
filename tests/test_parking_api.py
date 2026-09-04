from __future__ import annotations

import hashlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
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


def write_config(path: Path, name_prefix: str = "S") -> None:
    config = """allocation:
  weights:
    distance: 0.35
    congestion: 0.30
    waiting: 0.20
    fairness: 0.15
slots:
  - {id: 1, name: NAME1, walking_distance: 0.2, zone: north}
  - {id: 2, name: NAME2, walking_distance: 0.3, zone: north}
  - {id: 3, name: NAME3, walking_distance: 0.5, zone: central}
  - {id: 4, name: NAME4, walking_distance: 0.7, zone: south}
  - {id: 5, name: NAME5, walking_distance: 0.9, zone: south}
"""
    for slot_id in range(1, 6):
        config = config.replace(f"NAME{slot_id}", f"{name_prefix}{slot_id}")
    path.write_text(
        config,
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
    assert {
        "exit_idempotency_key",
        "entry_slot_name",
        "exit_slot_name",
    } <= columns
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


def test_exit_closes_session_frees_slot_and_replays_original_result(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        entered = client.post(
            "/api/vehicle/entry",
            json={"rfid_uid": "CARD-1", "idempotency_key": "entry-1"},
        ).json()
        exited = client.post(
            "/api/vehicle/exit",
            json={"rfid_uid": "CARD-1", "idempotency_key": "exit-1"},
        )
        replay = client.post(
            "/api/vehicle/exit",
            json={"rfid_uid": "CARD-1", "idempotency_key": "exit-1"},
        )

    assert exited.status_code == 200
    assert exited.json()["slot_id"] == entered["slot_id"]
    assert exited.json()["gate_action"] == "open"
    assert exited.json()["exited_at"].endswith("Z")
    assert replay.json() == exited.json()
    with sqlite3.connect(settings.database_path) as connection:
        session = connection.execute(
            "SELECT exited_at, exit_idempotency_key FROM parking_sessions"
        ).fetchone()
        occupied = connection.execute(
            "SELECT occupied FROM parking_slots WHERE id = ?", (entered["slot_id"],)
        ).fetchone()[0]
    assert session == (exited.json()["exited_at"], "exit-1")
    assert occupied == 0


def test_exit_without_active_session_is_rejected(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        response = client.post(
            "/api/vehicle/exit",
            json={"rfid_uid": "CARD-1", "idempotency_key": "exit-1"},
        )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "vehicle_not_parked"


def test_entry_key_cannot_be_reused_for_exit(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        client.post(
            "/api/vehicle/entry",
            json={"rfid_uid": "CARD-1", "idempotency_key": "shared-1"},
        )
        response = client.post(
            "/api/vehicle/exit",
            json={"rfid_uid": "CARD-1", "idempotency_key": "shared-1"},
        )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "idempotency_conflict"


def test_exit_key_cannot_be_reused_for_entry(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        client.post(
            "/api/vehicle/entry",
            json={"rfid_uid": "CARD-1", "idempotency_key": "entry-1"},
        )
        client.post(
            "/api/vehicle/exit",
            json={"rfid_uid": "CARD-1", "idempotency_key": "shared-1"},
        )
        response = client.post(
            "/api/vehicle/entry",
            json={"rfid_uid": "CARD-2", "idempotency_key": "shared-1"},
        )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "idempotency_conflict"


def test_exit_key_cannot_be_reused_for_another_vehicle(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        for card, key in (("CARD-1", "entry-1"), ("CARD-2", "entry-2")):
            client.post(
                "/api/vehicle/entry",
                json={"rfid_uid": card, "idempotency_key": key},
            )
        client.post(
            "/api/vehicle/exit",
            json={"rfid_uid": "CARD-1", "idempotency_key": "exit-1"},
        )
        response = client.post(
            "/api/vehicle/exit",
            json={"rfid_uid": "CARD-2", "idempotency_key": "exit-1"},
        )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "idempotency_conflict"


def test_status_returns_five_ordered_slots_with_active_session(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        entry = client.post(
            "/api/vehicle/entry",
            json={"rfid_uid": "CARD-1", "idempotency_key": "entry-1"},
        ).json()
        response = client.get("/api/parking/status")

    assert response.status_code == 200
    slots = response.json()["slots"]
    assert [slot["id"] for slot in slots] == [1, 2, 3, 4, 5]
    active = next(slot for slot in slots if slot["id"] == entry["slot_id"])
    assert active["occupied"] is True
    assert active["active_session_id"] == entry["session_id"]
    assert active["rfid_uid"] == "CARD-1"
    assert all(slot["updated_at"].endswith("Z") for slot in slots)


def test_concurrent_entries_receive_different_slots(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        def enter(card_number: int) -> tuple[int, int]:
            response = client.post(
                "/api/vehicle/entry",
                json={
                    "rfid_uid": f"CARD-{card_number}",
                    "idempotency_key": f"entry-{card_number}",
                },
            )
            return response.status_code, response.json()["slot_id"]

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(enter, (1, 2)))

    assert {status for status, _ in results} == {200}
    assert len({slot_id for _, slot_id in results}) == 2
    with sqlite3.connect(settings.database_path) as connection:
        active_count = connection.execute(
            "SELECT COUNT(*) FROM parking_sessions WHERE exited_at IS NULL"
        ).fetchone()[0]
    assert active_count == 2


@pytest.mark.parametrize("key_length", [122, 123, 128])
def test_maximum_length_entry_keys_have_bounded_scenario_ids(
    tmp_path: Path, key_length: int
) -> None:
    settings = make_settings(tmp_path)
    idempotency_key = "x" * key_length
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        response = client.post(
            "/api/vehicle/entry",
            json={"rfid_uid": "CARD-1", "idempotency_key": idempotency_key},
        )

    assert response.status_code == 200
    with sqlite3.connect(settings.database_path) as connection:
        scenario_id = connection.execute(
            "SELECT scenario_id FROM optimizer_runs"
        ).fetchone()[0]
    assert scenario_id == f"entry:{hashlib.sha256(idempotency_key.encode()).hexdigest()}"


def test_lifecycle_seed_uses_unsigned_sha256_prefix(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    idempotency_key = "vector-1"
    expected_seed = int.from_bytes(
        hashlib.sha256(f"CARD-1:{idempotency_key}".encode()).digest()[:8], "big"
    )
    with TestClient(create_app(settings)) as client:
        client.post(
            "/api/vehicle/entry",
            json={"rfid_uid": "CARD-1", "idempotency_key": idempotency_key},
        )
        response = client.get("/api/benchmarks/optimizers")

    assert response.json()["runs"][0]["seed"] == expected_seed


def test_replays_preserve_slot_name_after_configuration_change(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        entered = client.post(
            "/api/vehicle/entry",
            json={"rfid_uid": "CARD-1", "idempotency_key": "entry-1"},
        )
        exited = client.post(
            "/api/vehicle/exit",
            json={"rfid_uid": "CARD-1", "idempotency_key": "exit-1"},
        )

    write_config(settings.parking_config_path, name_prefix="RENAMED-")
    restarted = Settings(
        database_url=settings.database_url,
        parking_config_path=settings.parking_config_path,
    )
    with TestClient(create_app(restarted)) as client:
        entry_replay = client.post(
            "/api/vehicle/entry",
            json={"rfid_uid": "CARD-1", "idempotency_key": "entry-1"},
        )
        exit_replay = client.post(
            "/api/vehicle/exit",
            json={"rfid_uid": "CARD-1", "idempotency_key": "exit-1"},
        )

    assert entry_replay.json() == entered.json()
    assert exit_replay.json() == exited.json()
