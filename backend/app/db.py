from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from backend.app.config import SlotConfig
from backend.app.models.parking import EntryResponse, ParkingConflict, ParkingSlotRecord
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
    exit_idempotency_key TEXT,
    entered_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    exited_at TEXT,
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
            session_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(parking_sessions)")
            }
            if "exit_idempotency_key" not in session_columns:
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

    def enter_vehicle(
        self,
        rfid_uid: str,
        idempotency_key: str,
        allocate: Callable[[tuple[ParkingSlotRecord, ...]], AllocationResult],
    ) -> EntryResponse:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = connection.execute(
                """
                SELECT ps.id AS session_id, v.rfid_uid, ps.slot_id,
                       s.name AS slot_name, r.algorithm AS optimizer,
                       r.best_cost AS allocation_cost, ps.entered_at
                FROM parking_sessions AS ps
                JOIN vehicles AS v ON v.id = ps.vehicle_id
                JOIN parking_slots AS s ON s.id = ps.slot_id
                JOIN allocations AS a ON a.session_id = ps.id
                JOIN optimizer_runs AS r ON r.id = a.optimizer_run_id
                WHERE ps.entry_idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
            if replay is not None:
                if replay["rfid_uid"] != rfid_uid:
                    raise ParkingConflict(
                        "idempotency_conflict",
                        "idempotency key belongs to a different request",
                    )
                return EntryResponse.model_validate(dict(replay))

            exit_key = connection.execute(
                "SELECT 1 FROM parking_sessions WHERE exit_idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if exit_key is not None:
                raise ParkingConflict(
                    "idempotency_conflict",
                    "idempotency key belongs to a different operation",
                )

            connection.execute(
                "INSERT INTO vehicles (rfid_uid) VALUES (?) ON CONFLICT(rfid_uid) DO NOTHING",
                (rfid_uid,),
            )
            vehicle = connection.execute(
                "SELECT id FROM vehicles WHERE rfid_uid = ?", (rfid_uid,)
            ).fetchone()
            active = connection.execute(
                """
                SELECT 1 FROM parking_sessions
                WHERE vehicle_id = ? AND exited_at IS NULL
                """,
                (vehicle["id"],),
            ).fetchone()
            if active is not None:
                raise ParkingConflict(
                    "vehicle_already_parked",
                    "vehicle already has an active parking session",
                )
            slot_rows = connection.execute(
                """
                SELECT id, name, walking_distance, zone, occupied, updated_at
                FROM parking_slots ORDER BY id
                """
            ).fetchall()
            slots = tuple(ParkingSlotRecord.model_validate(dict(row)) for row in slot_rows)
            result = allocate(slots)

            optimizer_cursor = connection.execute(
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
                INSERT INTO parking_sessions (
                    vehicle_id, slot_id, entry_idempotency_key
                ) VALUES (?, ?, ?)
                """,
                (vehicle["id"], result.chosen_slot_id, idempotency_key),
            )
            session_id = int(session_cursor.lastrowid)
            connection.execute(
                """
                INSERT INTO allocations (
                    session_id, optimizer_run_id, slot_id, idempotency_key
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    session_id,
                    optimizer_cursor.lastrowid,
                    result.chosen_slot_id,
                    idempotency_key,
                ),
            )
            updated = connection.execute(
                """
                UPDATE parking_slots
                SET occupied = 1,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE id = ? AND occupied = 0
                """,
                (result.chosen_slot_id,),
            )
            if updated.rowcount != 1:
                raise ParkingConflict(
                    "no_available_slot",
                    "selected parking slot is no longer available",
                )
            stored = connection.execute(
                """
                SELECT ps.entered_at, s.name AS slot_name
                FROM parking_sessions AS ps
                JOIN parking_slots AS s ON s.id = ps.slot_id
                WHERE ps.id = ?
                """,
                (session_id,),
            ).fetchone()
            response = EntryResponse(
                session_id=session_id,
                rfid_uid=rfid_uid,
                slot_id=result.chosen_slot_id,
                slot_name=stored["slot_name"],
                optimizer=result.algorithm,
                allocation_cost=result.best_cost,
                entered_at=stored["entered_at"],
            )
        return response

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
