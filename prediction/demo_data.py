"""Deterministic, transactionally replaceable prediction demo history."""

from __future__ import annotations

import json
import math
import random
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from backend.app.db import Database
from prediction.models import WEATHER_CATEGORIES

DEFAULT_DATASET_KEY = "prediction-demo"
DEFAULT_SEED = 20260908
DEFAULT_START_AT = datetime(2026, 8, 1, tzinfo=UTC)
DEFAULT_DAYS = 14
INTERVAL_MINUTES = 5
_DATASET_KEY_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_OWNED_TABLES = (
    "allocations",
    "optimizer_runs",
    "parking_sessions",
    "vehicles",
    "context_samples",
)
_DELETE_OWNED_ROWS = (
    (
        "allocations",
        """
        DELETE FROM allocations
        WHERE id IN (
            SELECT row_id FROM prediction_demo_records
            WHERE dataset_key = ? AND table_name = 'allocations'
        )
        """,
    ),
    (
        "optimizer_runs",
        """
        DELETE FROM optimizer_runs
        WHERE id IN (
            SELECT row_id FROM prediction_demo_records
            WHERE dataset_key = ? AND table_name = 'optimizer_runs'
        )
        """,
    ),
    (
        "parking_sessions",
        """
        DELETE FROM parking_sessions
        WHERE id IN (
            SELECT row_id FROM prediction_demo_records
            WHERE dataset_key = ? AND table_name = 'parking_sessions'
        )
        """,
    ),
    (
        "vehicles",
        """
        DELETE FROM vehicles
        WHERE id IN (
            SELECT row_id FROM prediction_demo_records
            WHERE dataset_key = ? AND table_name = 'vehicles'
        )
        """,
    ),
    (
        "context_samples",
        """
        DELETE FROM context_samples
        WHERE id IN (
            SELECT row_id FROM prediction_demo_records
            WHERE dataset_key = ? AND table_name = 'context_samples'
        )
        """,
    ),
)


class DemoDataError(ValueError):
    """Demo-data validation error with a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class DemoDataConfig:
    dataset_key: str = DEFAULT_DATASET_KEY
    seed: int = DEFAULT_SEED
    start_at: datetime = DEFAULT_START_AT
    days: int = DEFAULT_DAYS

    def __post_init__(self) -> None:
        if not isinstance(self.dataset_key, str) or not _DATASET_KEY_PATTERN.fullmatch(
            self.dataset_key
        ):
            raise DemoDataError(
                "invalid_demo_config",
                "dataset_key must use letters, digits, hyphens, or underscores",
            )
        if not isinstance(self.seed, int) or isinstance(self.seed, bool):
            raise DemoDataError("invalid_demo_config", "seed must be an integer")
        if not isinstance(self.start_at, datetime):
            raise DemoDataError("invalid_demo_config", "start_at must be a UTC datetime")
        if self.start_at.tzinfo is None or self.start_at.utcoffset() != timedelta(0):
            raise DemoDataError("invalid_demo_config", "start_at must be timezone-aware UTC")
        if (
            self.start_at.second != 0
            or self.start_at.microsecond != 0
            or self.start_at.minute % INTERVAL_MINUTES != 0
        ):
            raise DemoDataError(
                "invalid_demo_config", "start_at must align to the five-minute interval"
            )
        if not isinstance(self.days, int) or isinstance(self.days, bool) or self.days < 1:
            raise DemoDataError(
                "invalid_demo_config", "days must provide at least one day of history"
            )


@dataclass(frozen=True)
class DemoDataSummary:
    dataset_key: str
    context_samples: int
    vehicles: int
    sessions: int
    optimizer_runs: int
    allocations: int

    def as_dict(self) -> dict[str, str | int]:
        return {
            "allocations": self.allocations,
            "context_samples": self.context_samples,
            "dataset_key": self.dataset_key,
            "optimizer_runs": self.optimizer_runs,
            "sessions": self.sessions,
            "vehicles": self.vehicles,
        }


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _record_owned_row(
    connection: sqlite3.Connection, dataset_key: str, table_name: str, row_id: int
) -> None:
    connection.execute(
        """
        INSERT INTO prediction_demo_records (dataset_key, table_name, row_id)
        VALUES (?, ?, ?)
        """,
        (dataset_key, table_name, row_id),
    )


def _delete_previous_dataset(connection: sqlite3.Connection, dataset_key: str) -> None:
    for _, statement in _DELETE_OWNED_ROWS:
        connection.execute(statement, (dataset_key,))
    connection.execute("DELETE FROM prediction_demo_records WHERE dataset_key = ?", (dataset_key,))


def _occupancy_count(
    timestamp: datetime,
    slot_count: int,
    weather: str,
    holiday: int,
    event: int,
    rng: random.Random,
) -> int:
    hour = timestamp.hour + timestamp.minute / 60
    daily_demand = max(0.0, math.sin(math.pi * (hour - 6) / 12))
    weekly_adjustment = (-0.12, 0.0, 0.03, 0.06, 0.04, -0.08, -0.15)[timestamp.weekday()]
    weather_adjustment = {"rain": -0.08, "storm": -0.18, "snow": -0.12, "fog": -0.04}.get(
        weather, 0.0
    )
    pulse = (0.22 if event else 0.0) - (0.10 if holiday else 0.0)
    seeded_variation = rng.uniform(-0.16, 0.16)
    ratio = 0.18 + 0.56 * daily_demand + weekly_adjustment + weather_adjustment + pulse
    return min(slot_count, max(0, round(slot_count * (ratio + seeded_variation))))


def _insert_demo_data(connection: sqlite3.Connection, config: DemoDataConfig) -> DemoDataSummary:
    slot_ids = tuple(
        int(row["id"])
        for row in connection.execute("SELECT id FROM parking_slots ORDER BY id").fetchall()
    )
    if not slot_ids:
        raise DemoDataError(
            "invalid_demo_database", "database must contain at least one parking slot"
        )

    unowned_active_session = connection.execute(
        """
        SELECT 1 FROM parking_sessions AS ps
        LEFT JOIN prediction_demo_records AS ownership
          ON ownership.dataset_key = ?
         AND ownership.table_name = 'parking_sessions'
         AND ownership.row_id = ps.id
        WHERE ps.exited_at IS NULL AND ownership.row_id IS NULL
        LIMIT 1
        """,
        (config.dataset_key,),
    ).fetchone()
    unowned_occupied_slot = connection.execute(
        """
        SELECT 1 FROM parking_slots AS slot
        LEFT JOIN parking_sessions AS ps
          ON ps.slot_id = slot.id AND ps.exited_at IS NULL
        LEFT JOIN prediction_demo_records AS ownership
          ON ownership.dataset_key = ?
         AND ownership.table_name = 'parking_sessions'
         AND ownership.row_id = ps.id
        WHERE slot.occupied = 1 AND (ps.id IS NULL OR ownership.row_id IS NULL)
        LIMIT 1
        """,
        (config.dataset_key,),
    ).fetchone()
    if unowned_active_session is not None or unowned_occupied_slot is not None:
        raise DemoDataError(
            "occupied_demo_database",
            "synthetic history requires a dedicated database without unrelated "
            "active parking state",
        )

    _delete_previous_dataset(connection, config.dataset_key)
    connection.execute("UPDATE parking_slots SET occupied = 0 WHERE occupied = 1")
    rng = random.Random(config.seed)
    interval = timedelta(minutes=INTERVAL_MINUTES)
    total_intervals = config.days * 24 * 60 // INTERVAL_MINUTES
    weather_cycle = WEATHER_CATEGORIES
    context_count = 0
    occupancy_counts: list[int] = []
    for index in range(total_intervals):
        sampled_at = config.start_at + index * interval
        day = index // (24 * 60 // INTERVAL_MINUTES)
        weather = weather_cycle[index % len(weather_cycle)]
        holiday = int(day % 7 == 0 and 8 <= sampled_at.hour < 18)
        event = int(day % 5 == 2 and 17 <= sampled_at.hour < 21)
        occupancy_count = _occupancy_count(sampled_at, len(slot_ids), weather, holiday, event, rng)
        cursor = connection.execute(
            """
            INSERT INTO context_samples (occupancy_count, weather, holiday, event, sampled_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                occupancy_count,
                weather,
                holiday,
                event,
                _timestamp(sampled_at),
            ),
        )
        _record_owned_row(connection, config.dataset_key, "context_samples", int(cursor.lastrowid))
        context_count += 1
        occupancy_counts.append(occupancy_count)

    active_sessions: dict[int, int] = {}
    vehicle_count = 0
    session_count = optimizer_run_count = allocation_count = 0
    for index, target_occupancy in enumerate(occupancy_counts):
        entered_at = config.start_at + index * interval
        while len(active_sessions) > target_occupancy:
            slot_id = rng.choice(tuple(active_sessions))
            session_id = active_sessions.pop(slot_id)
            connection.execute(
                "UPDATE parking_sessions SET exited_at = ? WHERE id = ?",
                (_timestamp(entered_at), session_id),
            )
            connection.execute(
                "UPDATE parking_slots SET occupied = 0, updated_at = ? WHERE id = ?",
                (_timestamp(entered_at), slot_id),
            )
        while len(active_sessions) < target_occupancy:
            slot_id = next(slot for slot in slot_ids if slot not in active_sessions)
            vehicle_count += 1
            vehicle = connection.execute(
                "INSERT INTO vehicles (rfid_uid, created_at) VALUES (?, ?)",
                (f"demo-rfid-{config.dataset_key}-{vehicle_count:05d}", _timestamp(entered_at)),
            )
            vehicle_id = int(vehicle.lastrowid)
            _record_owned_row(connection, config.dataset_key, "vehicles", vehicle_id)
            objective = {
                "congestion": round(rng.uniform(0.0, 1.0), 6),
                "distance": round(rng.uniform(0.0, 1.0), 6),
                "fairness": round(rng.uniform(0.0, 1.0), 6),
                "waiting": round(rng.uniform(0.0, 1.0), 6),
            }
            best_cost = (
                0.35 * objective["distance"]
                + 0.30 * objective["congestion"]
                + 0.20 * objective["waiting"]
                + 0.15 * objective["fairness"]
            )
            optimizer = connection.execute(
                """
                INSERT INTO optimizer_runs (
                    algorithm, scenario_id, chosen_slot_id, best_cost, iterations,
                    runtime_ms, objective_breakdown, seed, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "demo",
                    f"prediction-demo-{config.dataset_key}-{session_count}",
                    slot_id,
                    round(best_cost, 6),
                    10 + rng.randrange(20),
                    round(rng.uniform(0.1, 3.0), 6),
                    json.dumps(objective, sort_keys=True),
                    str(config.seed),
                    _timestamp(entered_at),
                ),
            )
            optimizer_id = int(optimizer.lastrowid)
            _record_owned_row(connection, config.dataset_key, "optimizer_runs", optimizer_id)
            optimizer_run_count += 1
            session = connection.execute(
                """
                INSERT INTO parking_sessions (
                    vehicle_id, slot_id, entry_idempotency_key, exit_idempotency_key,
                    entry_slot_name, exit_slot_name, entered_at, exited_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    vehicle_id,
                    slot_id,
                    f"prediction-demo-entry-{config.dataset_key}-{session_count}",
                    f"prediction-demo-exit-{config.dataset_key}-{session_count}",
                    f"demo-slot-{slot_id}",
                    f"demo-slot-{slot_id}",
                    _timestamp(entered_at),
                ),
            )
            session_id = int(session.lastrowid)
            active_sessions[slot_id] = session_id
            connection.execute(
                "UPDATE parking_slots SET occupied = 1, updated_at = ? WHERE id = ?",
                (_timestamp(entered_at), slot_id),
            )
            _record_owned_row(connection, config.dataset_key, "parking_sessions", session_id)
            allocation = connection.execute(
                """
                INSERT INTO allocations (
                    session_id, optimizer_run_id, slot_id, idempotency_key, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    optimizer_id,
                    slot_id,
                    f"prediction-demo-allocation-{config.dataset_key}-{allocation_count}",
                    _timestamp(entered_at),
                ),
            )
            _record_owned_row(
                connection, config.dataset_key, "allocations", int(allocation.lastrowid)
            )
            allocation_count += 1
            session_count += 1

    return DemoDataSummary(
        dataset_key=config.dataset_key,
        context_samples=context_count,
        vehicles=vehicle_count,
        sessions=session_count,
        optimizer_runs=optimizer_run_count,
        allocations=allocation_count,
    )


def replace_prediction_demo_data(database: Database, config: DemoDataConfig) -> DemoDataSummary:
    """Replace only rows owned by ``config.dataset_key`` in one immediate transaction."""
    if not isinstance(database, Database):
        raise DemoDataError("invalid_demo_database", "database must be initialized")
    if not isinstance(config, DemoDataConfig):
        raise DemoDataError("invalid_demo_config", "config must be a DemoDataConfig")
    return database.run_prediction_demo_transaction(
        lambda connection: _insert_demo_data(connection, config)
    )
