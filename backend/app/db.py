from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from backend.app.config import SlotConfig
from backend.app.models.parking import (
    EntryResponse,
    ExitResponse,
    ParkingConflict,
    ParkingSlotRecord,
    ParkingSlotStatus,
    ParkingStatusResponse,
)
from optimization.models import AllocationResult, PersistedOptimizerRun

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS parking_slots (
    id INTEGER PRIMARY KEY CHECK (id BETWEEN 1 AND 5),
    name TEXT NOT NULL UNIQUE,
    walking_distance REAL NOT NULL CHECK (walking_distance BETWEEN 0 AND 1),
    zone TEXT NOT NULL,
    occupied INTEGER NOT NULL DEFAULT 0 CHECK (occupied IN (0, 1)),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS vehicles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rfid_uid TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS parking_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vehicle_id INTEGER NOT NULL REFERENCES vehicles(id),
    slot_id INTEGER NOT NULL REFERENCES parking_slots(id),
    entry_idempotency_key TEXT NOT NULL UNIQUE,
    entered_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    exited_at TEXT,
    exit_idempotency_key TEXT,
    CHECK (exited_at IS NULL OR exited_at >= entered_at)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_session_per_vehicle
    ON parking_sessions(vehicle_id) WHERE exited_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS one_active_session_per_slot
    ON parking_sessions(slot_id) WHERE exited_at IS NULL;

CREATE TABLE IF NOT EXISTS occupancy_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slot_id INTEGER NOT NULL REFERENCES parking_slots(id),
    occupied INTEGER NOT NULL CHECK (occupied IN (0, 1)),
    confidence REAL CHECK (confidence BETWEEN 0 AND 1),
    source TEXT NOT NULL,
    observed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS context_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    occupancy_count INTEGER NOT NULL CHECK (occupancy_count BETWEEN 0 AND 5),
    weather TEXT NOT NULL,
    holiday INTEGER NOT NULL CHECK (holiday IN (0, 1)),
    event INTEGER NOT NULL CHECK (event IN (0, 1)),
    sampled_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS optimizer_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    algorithm TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    chosen_slot_id INTEGER REFERENCES parking_slots(id),
    best_cost REAL,
    iterations INTEGER NOT NULL,
    runtime_ms REAL NOT NULL,
    objective_breakdown TEXT NOT NULL,
    seed INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES parking_sessions(id),
    optimizer_run_id INTEGER REFERENCES optimizer_runs(id),
    slot_id INTEGER NOT NULL REFERENCES parking_slots(id),
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS prediction_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model TEXT NOT NULL,
    split_id TEXT NOT NULL,
    mae REAL NOT NULL,
    rmse REAL NOT NULL,
    mse REAL NOT NULL,
    inference_latency_ms REAL NOT NULL,
    artifact_metadata TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self, slots: Sequence[SlotConfig]) -> None:
        if len(slots) != 5:
            raise ValueError("database initialization requires exactly five slots")
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(parking_sessions)")
            }
            if "exit_idempotency_key" not in columns:
                connection.execute(
                    "ALTER TABLE parking_sessions ADD COLUMN exit_idempotency_key TEXT"
                )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS unique_exit_idempotency_key
                ON parking_sessions(exit_idempotency_key)
                WHERE exit_idempotency_key IS NOT NULL
                """
            )
            connection.executemany(
                """
                INSERT INTO parking_slots (id, name, walking_distance, zone)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    walking_distance = excluded.walking_distance,
                    zone = excluded.zone
                """,
                [(slot.id, slot.name, slot.walking_distance, slot.zone) for slot in slots],
            )

    def slot_count(self) -> int:
        with self.connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM parking_slots").fetchone()
        return int(row["count"] if row else 0)

    def save_optimizer_results(self, results: Sequence[AllocationResult]) -> None:
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO optimizer_runs (
                    algorithm, scenario_id, chosen_slot_id, best_cost, iterations,
                    runtime_ms, objective_breakdown, seed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        result.algorithm,
                        result.scenario_id,
                        result.chosen_slot_id,
                        result.best_cost,
                        result.iterations,
                        result.runtime_ms,
                        json.dumps(result.objective_breakdown.model_dump(), sort_keys=True),
                        result.seed,
                    )
                    for result in results
                ],
            )

    def list_optimizer_results(self) -> list[PersistedOptimizerRun]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT algorithm, scenario_id, chosen_slot_id, best_cost, iterations,
                       runtime_ms, objective_breakdown, seed, created_at
                FROM optimizer_runs ORDER BY id DESC
                """
            ).fetchall()
        return [
            PersistedOptimizerRun.model_validate(
                {
                    **dict(row),
                    "objective_breakdown": json.loads(row["objective_breakdown"]),
                }
            )
            for row in rows
        ]

    def enter_vehicle(
        self,
        rfid_uid: str,
        idempotency_key: str,
        allocate: Callable[[tuple[ParkingSlotRecord, ...]], AllocationResult],
    ) -> EntryResponse:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT ps.id AS session_id, v.rfid_uid, s.id AS slot_id,
                       s.name AS slot_name, r.algorithm AS optimizer,
                       r.best_cost AS allocation_cost, ps.entered_at
                FROM parking_sessions ps
                JOIN vehicles v ON v.id = ps.vehicle_id
                JOIN parking_slots s ON s.id = ps.slot_id
                JOIN allocations a ON a.session_id = ps.id
                JOIN optimizer_runs r ON r.id = a.optimizer_run_id
                WHERE ps.entry_idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                if existing["rfid_uid"] != rfid_uid:
                    raise ParkingConflict(
                        "idempotency_conflict",
                        "idempotency key is already used by another operation",
                    )
                return EntryResponse.model_validate(dict(existing))
            exit_key = connection.execute(
                "SELECT 1 FROM parking_sessions WHERE exit_idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if exit_key is not None:
                raise ParkingConflict(
                    "idempotency_conflict",
                    "idempotency key is already used by another operation",
                )
            active = connection.execute(
                """
                SELECT 1 FROM parking_sessions ps
                JOIN vehicles v ON v.id = ps.vehicle_id
                WHERE v.rfid_uid = ? AND ps.exited_at IS NULL
                """,
                (rfid_uid,),
            ).fetchone()
            if active is not None:
                raise ParkingConflict(
                    "vehicle_already_parked", "vehicle already has an active parking session"
                )
            connection.execute(
                "INSERT OR IGNORE INTO vehicles (rfid_uid) VALUES (?)", (rfid_uid,)
            )
            vehicle = connection.execute(
                "SELECT id FROM vehicles WHERE rfid_uid = ?", (rfid_uid,)
            ).fetchone()
            rows = connection.execute(
                """
                SELECT id, name, walking_distance, zone, occupied, updated_at
                FROM parking_slots ORDER BY id
                """
            ).fetchall()
            slots = tuple(ParkingSlotRecord.model_validate(dict(row)) for row in rows)
            result = allocate(slots)
            run_cursor = connection.execute(
                """
                INSERT INTO optimizer_runs (
                    algorithm, scenario_id, chosen_slot_id, best_cost, iterations,
                    runtime_ms, objective_breakdown, seed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.algorithm,
                    result.scenario_id,
                    result.chosen_slot_id,
                    result.best_cost,
                    result.iterations,
                    result.runtime_ms,
                    json.dumps(result.objective_breakdown.model_dump(), sort_keys=True),
                    result.seed,
                ),
            )
            session_cursor = connection.execute(
                """
                INSERT INTO parking_sessions (vehicle_id, slot_id, entry_idempotency_key)
                VALUES (?, ?, ?)
                """,
                (vehicle["id"], result.chosen_slot_id, idempotency_key),
            )
            connection.execute(
                """
                INSERT INTO allocations (session_id, optimizer_run_id, slot_id, idempotency_key)
                VALUES (?, ?, ?, ?)
                """,
                (
                    session_cursor.lastrowid,
                    run_cursor.lastrowid,
                    result.chosen_slot_id,
                    idempotency_key,
                ),
            )
            connection.execute(
                """
                UPDATE parking_slots
                SET occupied = 1, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (result.chosen_slot_id,),
            )
            saved = connection.execute(
                """
                SELECT ps.id AS session_id, v.rfid_uid, s.id AS slot_id,
                       s.name AS slot_name, ps.entered_at
                FROM parking_sessions ps
                JOIN vehicles v ON v.id = ps.vehicle_id
                JOIN parking_slots s ON s.id = ps.slot_id
                WHERE ps.id = ?
                """,
                (session_cursor.lastrowid,),
            ).fetchone()
        return EntryResponse(
            **dict(saved), optimizer=result.algorithm, allocation_cost=result.best_cost
        )

    def exit_vehicle(self, rfid_uid: str, idempotency_key: str) -> ExitResponse:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            entry_key = connection.execute(
                "SELECT 1 FROM parking_sessions WHERE entry_idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if entry_key is not None:
                raise ParkingConflict(
                    "idempotency_conflict",
                    "idempotency key is already used by another operation",
                )
            existing = connection.execute(
                """
                SELECT ps.id AS session_id, v.rfid_uid, s.id AS slot_id,
                       s.name AS slot_name, ps.exited_at
                FROM parking_sessions ps
                JOIN vehicles v ON v.id = ps.vehicle_id
                JOIN parking_slots s ON s.id = ps.slot_id
                WHERE ps.exit_idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
            if existing is not None:
                if existing["rfid_uid"] != rfid_uid:
                    raise ParkingConflict(
                        "idempotency_conflict",
                        "idempotency key is already used by another operation",
                    )
                return ExitResponse.model_validate(dict(existing))
            active = connection.execute(
                """
                SELECT ps.id AS session_id, ps.slot_id, v.rfid_uid, s.name AS slot_name
                FROM parking_sessions ps
                JOIN vehicles v ON v.id = ps.vehicle_id
                JOIN parking_slots s ON s.id = ps.slot_id
                WHERE v.rfid_uid = ? AND ps.exited_at IS NULL
                """,
                (rfid_uid,),
            ).fetchone()
            if active is None:
                raise ParkingConflict(
                    "vehicle_not_parked", "vehicle does not have an active parking session"
                )
            connection.execute(
                """
                UPDATE parking_sessions
                SET exited_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                    exit_idempotency_key = ?
                WHERE id = ?
                """,
                (idempotency_key, active["session_id"]),
            )
            connection.execute(
                """
                UPDATE parking_slots
                SET occupied = 0, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ?
                """,
                (active["slot_id"],),
            )
            exited_at = connection.execute(
                "SELECT exited_at FROM parking_sessions WHERE id = ?",
                (active["session_id"],),
            ).fetchone()["exited_at"]
        return ExitResponse(
            session_id=active["session_id"],
            rfid_uid=active["rfid_uid"],
            slot_id=active["slot_id"],
            slot_name=active["slot_name"],
            exited_at=exited_at,
        )

    def parking_status(self) -> ParkingStatusResponse:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT s.id, s.name, s.walking_distance, s.zone, s.occupied,
                       s.updated_at, ps.id AS active_session_id, v.rfid_uid
                FROM parking_slots s
                LEFT JOIN parking_sessions ps
                    ON ps.slot_id = s.id AND ps.exited_at IS NULL
                LEFT JOIN vehicles v ON v.id = ps.vehicle_id
                ORDER BY s.id
                """
            ).fetchall()
        statuses = tuple(ParkingSlotStatus.model_validate(dict(row)) for row in rows)
        return ParkingStatusResponse(slots=statuses)
