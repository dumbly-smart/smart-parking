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


def test_database_initialization_is_idempotent_and_creates_planned_tables(
    tmp_path: Path,
) -> None:
    settings = make_settings(tmp_path)
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
    assert slots == [(1, "S1", 0), (2, "S2", 0), (3, "S3", 0), (4, "S4", 0), (5, "S5", 0)]


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
