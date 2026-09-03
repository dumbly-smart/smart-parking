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


def write_config(path: Path, slot_count: int = 5, distance_weight: float = 0.35) -> None:
    slots = "\n".join(
        f'  - id: {index}\n    name: "S{index}"\n'
        f'    walking_distance: {index / 5:.1f}\n    zone: "zone-{index}"'
        for index in range(1, slot_count + 1)
    )
    path.write_text(
        "allocation:\n"
        f"  weights:\n    distance: {distance_weight}\n    congestion: 0.30\n"
        "    waiting: 0.20\n    fairness: 0.15\n"
        f"slots:\n{slots}\n",
        encoding="utf-8",
    )


def make_settings(tmp_path: Path) -> Settings:
    config_path = tmp_path / "parking.yaml"
    write_config(config_path)
    return Settings(
        mode="demo",
        database_url=f"sqlite:///{tmp_path / 'parking.db'}",
        parking_config_path=config_path,
    )


def test_settings_load_exactly_five_slots_and_default_weights(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)

    assert len(settings.parking.slots) == 5
    assert settings.parking.allocation.weights.model_dump() == {
        "distance": 0.35,
        "congestion": 0.30,
        "waiting": 0.20,
        "fairness": 0.15,
    }


@pytest.mark.parametrize(
    ("slot_count", "distance_weight"),
    [(4, 0.35), (6, 0.35), (5, 0.40)],
)
def test_settings_reject_invalid_slot_count_or_weights(
    tmp_path: Path, slot_count: int, distance_weight: float
) -> None:
    config_path = tmp_path / "invalid.yaml"
    write_config(config_path, slot_count=slot_count, distance_weight=distance_weight)

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


def test_health_reports_database_and_five_slots(tmp_path: Path) -> None:
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
