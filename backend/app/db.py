from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from backend.app.config import SlotConfig
from backend.app.models.occupancy import OccupancyPersistenceResult, OccupancyTransition
from backend.app.models.parking import (
    EntryResponse,
    ExitResponse,
    ParkingConflict,
    ParkingSlotRecord,
    ParkingSlotStatus,
    ParkingStatusResponse,
)
from optimization.models import AllocationResult, PersistedOptimizerRun
from prediction.models import (
    AllocationFeatureRecord,
    ContextSampleRecord,
    PredictionSourceData,
    SessionRecord,
)
from prediction.training import (
    EvaluationMetrics,
    ModelFamily,
    PersistedPredictionRun,
    PredictionTrainingError,
    TrainingResult,
)

PARKING_SLOTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS parking_slots (
    id INTEGER PRIMARY KEY CHECK (id >= 1),
    name TEXT NOT NULL UNIQUE,
    walking_distance REAL NOT NULL CHECK (walking_distance BETWEEN 0 AND 1),
    zone TEXT NOT NULL,
    occupied INTEGER NOT NULL DEFAULT 0 CHECK (occupied IN (0, 1)),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
"""

DEPENDENT_SCHEMA = """
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
    entry_slot_name TEXT,
    exit_slot_name TEXT,
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
    occupancy_count INTEGER NOT NULL CHECK (occupancy_count >= 0),
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
    seed TEXT NOT NULL,
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

CREATE TABLE IF NOT EXISTS prediction_demo_records (
    dataset_key TEXT NOT NULL,
    table_name TEXT NOT NULL CHECK (table_name IN (
        'context_samples', 'vehicles', 'parking_sessions', 'optimizer_runs', 'allocations'
    )),
    row_id INTEGER NOT NULL CHECK (row_id >= 1),
    PRIMARY KEY (dataset_key, table_name, row_id)
);
"""

_TransactionResult = TypeVar("_TransactionResult")


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._slot_order: tuple[int, ...] = ()

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

    def run_prediction_demo_transaction(
        self, operation: Callable[[sqlite3.Connection], _TransactionResult]
    ) -> _TransactionResult:
        """Run prediction demo replacement under one reserved transaction."""
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            return operation(connection)

    def initialize(self, slots: Sequence[SlotConfig]) -> None:
        if not slots:
            raise ValueError("database initialization requires at least one parking slot")
        slot_order = tuple(slot.id for slot in slots)
        with self.connect() as connection:
            self._migrate_legacy_parking_slots(connection)
            self._migrate_legacy_context_samples(connection)
            connection.executescript(PARKING_SLOTS_SCHEMA)
            connection.executescript(DEPENDENT_SCHEMA)
            session_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(parking_sessions)")
            }
            for column in (
                "exit_idempotency_key",
                "entry_slot_name",
                "exit_slot_name",
            ):
                if column not in session_columns:
                    connection.execute(
                        f"ALTER TABLE parking_sessions ADD COLUMN {column} TEXT"
                    )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS unique_exit_idempotency_key
                ON parking_sessions(exit_idempotency_key)
                WHERE exit_idempotency_key IS NOT NULL
                """
            )
            connection.execute("BEGIN IMMEDIATE")
            persisted_slots = connection.execute(
                "SELECT id, name FROM parking_slots ORDER BY id"
            ).fetchall()
            persisted_ids = {int(row["id"]) for row in persisted_slots}
            unconfigured_ids = persisted_ids - set(slot_order)
            if unconfigured_ids:
                formatted_ids = ", ".join(str(slot_id) for slot_id in sorted(unconfigured_ids))
                raise ValueError(
                    f"persisted parking slot IDs are absent from configuration: {formatted_ids}"
                )
            used_names = {str(row["name"]) for row in persisted_slots} | {
                slot.name for slot in slots
            }
            temporary_names: list[tuple[str, int]] = []
            candidate_number = 1
            for row in persisted_slots:
                candidate = f"__smart_parking_seed_{candidate_number}__"
                while candidate in used_names:
                    candidate_number += 1
                    candidate = f"__smart_parking_seed_{candidate_number}__"
                used_names.add(candidate)
                temporary_names.append((candidate, int(row["id"])))
                candidate_number += 1
            connection.executemany(
                "UPDATE parking_slots SET name = ? WHERE id = ?",
                temporary_names,
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
        self._slot_order = slot_order

    @staticmethod
    def _migrate_legacy_parking_slots(connection: sqlite3.Connection) -> None:
        schema_row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'parking_slots'"
        ).fetchone()
        if schema_row is None or "BETWEEN 1 AND 5" not in schema_row["sql"].upper():
            return

        index_statements = [
            row["sql"]
            for row in connection.execute(
                """
                SELECT sql FROM sqlite_master
                WHERE type = 'index' AND tbl_name = 'parking_slots' AND sql IS NOT NULL
                ORDER BY name
                """
            )
        ]
        connection.execute("PRAGMA foreign_keys = OFF")
        try:
            connection.execute("BEGIN")
            connection.execute(
                """
                CREATE TABLE parking_slots_new (
                    id INTEGER PRIMARY KEY CHECK (id >= 1),
                    name TEXT NOT NULL UNIQUE,
                    walking_distance REAL NOT NULL CHECK (walking_distance BETWEEN 0 AND 1),
                    zone TEXT NOT NULL,
                    occupied INTEGER NOT NULL DEFAULT 0 CHECK (occupied IN (0, 1)),
                    updated_at TEXT NOT NULL DEFAULT (
                        strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    )
                )
                """
            )
            connection.execute(
                """
                INSERT INTO parking_slots_new (
                    id, name, walking_distance, zone, occupied, updated_at
                )
                SELECT id, name, walking_distance, zone, occupied, updated_at
                FROM parking_slots
                """
            )
            connection.execute("DROP TABLE parking_slots")
            connection.execute("ALTER TABLE parking_slots_new RENAME TO parking_slots")
            for statement in index_statements:
                connection.execute(statement)
            foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
            if foreign_key_errors:
                raise sqlite3.IntegrityError(
                    "parking slot migration produced foreign key violations"
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.execute("PRAGMA foreign_keys = ON")

    @staticmethod
    def _migrate_legacy_context_samples(connection: sqlite3.Connection) -> None:
        schema_row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'context_samples'"
        ).fetchone()
        if schema_row is None or "BETWEEN 0 AND 5" not in schema_row["sql"].upper():
            return

        index_statements = [
            row["sql"]
            for row in connection.execute(
                """
                SELECT sql FROM sqlite_master
                WHERE type = 'index' AND tbl_name = 'context_samples' AND sql IS NOT NULL
                ORDER BY name
                """
            )
        ]
        try:
            connection.execute("BEGIN")
            connection.execute(
                """
                CREATE TABLE context_samples_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    occupancy_count INTEGER NOT NULL CHECK (occupancy_count >= 0),
                    weather TEXT NOT NULL,
                    holiday INTEGER NOT NULL CHECK (holiday IN (0, 1)),
                    event INTEGER NOT NULL CHECK (event IN (0, 1)),
                    sampled_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO context_samples_new (
                    id, occupancy_count, weather, holiday, event, sampled_at
                )
                SELECT id, occupancy_count, weather, holiday, event, sampled_at
                FROM context_samples
                """
            )
            connection.execute("DROP TABLE context_samples")
            connection.execute("ALTER TABLE context_samples_new RENAME TO context_samples")
            for statement in index_statements:
                connection.execute(statement)
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    def slot_count(self) -> int:
        with self.connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM parking_slots").fetchone()
        return int(row["count"] if row else 0)

    def load_prediction_source_data(self) -> PredictionSourceData:
        with self.connect() as connection:
            connection.execute("BEGIN")
            slot_count = int(
                connection.execute("SELECT COUNT(*) FROM parking_slots").fetchone()[0]
            )
            contexts = connection.execute(
                """
                SELECT id, occupancy_count, weather, holiday, event, sampled_at
                FROM context_samples ORDER BY sampled_at, id
                """
            ).fetchall()
            sessions = connection.execute(
                """
                SELECT id, vehicle_id, entered_at, exited_at
                FROM parking_sessions ORDER BY entered_at, id
                """
            ).fetchall()
            allocations = connection.execute(
                """
                SELECT a.id, ps.vehicle_id, a.created_at, r.objective_breakdown
                FROM allocations AS a
                JOIN parking_sessions AS ps ON ps.id = a.session_id
                JOIN optimizer_runs AS r ON r.id = a.optimizer_run_id
                ORDER BY a.created_at, a.id
                """
            ).fetchall()
        return PredictionSourceData(
            slot_count=slot_count,
            context_samples=tuple(ContextSampleRecord(**dict(row)) for row in contexts),
            sessions=tuple(SessionRecord(**dict(row)) for row in sessions),
            allocations=tuple(
                AllocationFeatureRecord(
                    id=row["id"],
                    vehicle_id=row["vehicle_id"],
                    created_at=row["created_at"],
                    objective_breakdown_json=row["objective_breakdown"],
                )
                for row in allocations
            ),
        )

    def apply_occupancy_transitions(
        self,
        transitions: Sequence[OccupancyTransition],
        observed_at: str,
        expected_occupancy: Mapping[int, bool],
    ) -> OccupancyPersistenceResult:
        blocked: set[int] = set()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            slots: dict[int, sqlite3.Row] = {}
            for slot_id in expected_occupancy:
                row = connection.execute(
                    """
                    SELECT s.occupied,
                           EXISTS (
                               SELECT 1 FROM parking_sessions AS ps
                               WHERE ps.slot_id = s.id AND ps.exited_at IS NULL
                           ) AS has_active_session
                    FROM parking_slots AS s
                    WHERE s.id = ?
                    """,
                    (slot_id,),
                ).fetchone()
                if row is None:
                    raise LookupError(f"unknown parking slot ID {slot_id}")
                slots[slot_id] = row
            if any(
                bool(slots[slot_id]["occupied"]) != expected
                for slot_id, expected in expected_occupancy.items()
            ):
                return OccupancyPersistenceResult(
                    snapshot_matched=False,
                    blocked_slot_ids=frozenset(),
                    occupied_slot_ids=frozenset(
                        slot_id for slot_id, slot in slots.items() if bool(slot["occupied"])
                    ),
                )

            for transition in transitions:
                slot = slots.get(transition.slot_id)
                if slot is None:
                    raise ValueError(
                        f"transition for unobserved parking slot ID {transition.slot_id}"
                    )
                if not transition.occupied and bool(slot["has_active_session"]):
                    blocked.add(transition.slot_id)
                    continue
                current_occupied = bool(slot["occupied"])
                if transition.occupied == current_occupied:
                    continue
                updated = connection.execute(
                    """
                    UPDATE parking_slots
                    SET occupied = ?, updated_at = ?
                    WHERE id = ? AND occupied = ?
                    """,
                    (
                        transition.occupied,
                        observed_at,
                        transition.slot_id,
                        current_occupied,
                    ),
                )
                if updated.rowcount != 1:
                    raise RuntimeError(
                        f"parking slot {transition.slot_id} changed concurrently"
                    )
                connection.execute(
                    """
                    INSERT INTO occupancy_events
                        (slot_id, occupied, confidence, source, observed_at)
                    VALUES (?, ?, ?, 'camera_heuristic', ?)
                    """,
                    (
                        transition.slot_id,
                        transition.occupied,
                        transition.confidence,
                        observed_at,
                    ),
                )
            occupied_slot_ids = frozenset(
                int(row["id"])
                for row in connection.execute(
                    "SELECT id FROM parking_slots WHERE occupied = 1"
                )
                if int(row["id"]) in expected_occupancy
            )
        return OccupancyPersistenceResult(
            snapshot_matched=True,
            blocked_slot_ids=frozenset(blocked),
            occupied_slot_ids=occupied_slot_ids,
        )

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
                       COALESCE(ps.entry_slot_name, s.name) AS slot_name,
                       r.algorithm AS optimizer,
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
            slot_name = next(slot.name for slot in slots if slot.id == result.chosen_slot_id)

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
                    self._encode_seed(result.seed),
                ),
            )
            session_cursor = connection.execute(
                """
                INSERT INTO parking_sessions (
                    vehicle_id, slot_id, entry_idempotency_key, entry_slot_name
                ) VALUES (?, ?, ?, ?)
                """,
                (vehicle["id"], result.chosen_slot_id, idempotency_key, slot_name),
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
                "SELECT entered_at FROM parking_sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            response = EntryResponse(
                session_id=session_id,
                rfid_uid=rfid_uid,
                slot_id=result.chosen_slot_id,
                slot_name=slot_name,
                optimizer=result.algorithm,
                allocation_cost=result.best_cost,
                entered_at=stored["entered_at"],
            )
        return response

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
                    "idempotency key belongs to a different operation",
                )

            replay = connection.execute(
                """
                SELECT ps.id AS session_id, v.rfid_uid, ps.slot_id,
                       COALESCE(ps.exit_slot_name, s.name) AS slot_name,
                       ps.exited_at
                FROM parking_sessions AS ps
                JOIN vehicles AS v ON v.id = ps.vehicle_id
                JOIN parking_slots AS s ON s.id = ps.slot_id
                WHERE ps.exit_idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()
            if replay is not None:
                if replay["rfid_uid"] != rfid_uid:
                    raise ParkingConflict(
                        "idempotency_conflict",
                        "idempotency key belongs to a different request",
                    )
                return ExitResponse.model_validate(dict(replay))

            active = connection.execute(
                """
                SELECT ps.id AS session_id, ps.slot_id, s.name AS slot_name
                FROM parking_sessions AS ps
                JOIN vehicles AS v ON v.id = ps.vehicle_id
                JOIN parking_slots AS s ON s.id = ps.slot_id
                WHERE v.rfid_uid = ? AND ps.exited_at IS NULL
                """,
                (rfid_uid,),
            ).fetchone()
            if active is None:
                raise ParkingConflict(
                    "vehicle_not_parked",
                    "vehicle does not have an active parking session",
                )

            exited_at = datetime.now(UTC).isoformat(timespec="milliseconds").replace(
                "+00:00", "Z"
            )
            connection.execute(
                """
                UPDATE parking_sessions
                SET exited_at = ?, exit_idempotency_key = ?, exit_slot_name = ?
                WHERE id = ? AND exited_at IS NULL
                """,
                (
                    exited_at,
                    idempotency_key,
                    active["slot_name"],
                    active["session_id"],
                ),
            )
            connection.execute(
                """
                UPDATE parking_slots SET occupied = 0, updated_at = ? WHERE id = ?
                """,
                (exited_at, active["slot_id"]),
            )
            response = ExitResponse(
                session_id=active["session_id"],
                rfid_uid=rfid_uid,
                slot_id=active["slot_id"],
                slot_name=active["slot_name"],
                exited_at=exited_at,
            )
        return response

    def parking_status(self) -> ParkingStatusResponse:
        order_expression = "CASE s.id " + " ".join(
            f"WHEN ? THEN {position}" for position in range(len(self._slot_order))
        ) + " ELSE ? END"
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT s.id, s.name, s.walking_distance, s.zone, s.occupied,
                       s.updated_at, ps.id AS active_session_id, v.rfid_uid
                FROM parking_slots AS s
                LEFT JOIN parking_sessions AS ps
                    ON ps.slot_id = s.id AND ps.exited_at IS NULL
                LEFT JOIN vehicles AS v ON v.id = ps.vehicle_id
                ORDER BY {order_expression}
                """,
                (*self._slot_order, len(self._slot_order)),
            ).fetchall()
        return ParkingStatusResponse(
            slots=tuple(ParkingSlotStatus.model_validate(dict(row)) for row in rows)
        )

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
                        self._encode_seed(result.seed),
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
                    "seed": self._decode_seed(row["seed"]),
                }
            )
            for row in rows
        ]

    def save_prediction_results(self, results: Sequence[TrainingResult]) -> None:
        """Atomically persist only artifact manifests that validate from disk."""
        from prediction.artifacts import load_manifest

        resolved = tuple(results)
        if not resolved or any(not isinstance(result, TrainingResult) for result in resolved):
            raise PredictionTrainingError(
                "invalid_manifest", "prediction persistence requires completed training results"
            )
        rows: list[tuple[object, ...]] = []
        for result in resolved:
            manifest = load_manifest(result.manifest_path)
            manifest_filename = result.manifest_path.name
            if (
                Path(manifest_filename).name != manifest_filename
                or not manifest_filename.endswith(".json")
            ):
                raise PredictionTrainingError(
                    "invalid_manifest", "manifest filename must be a safe basename"
                )
            if (
                manifest.model != result.model
                or manifest.split_id != result.split_id
                or manifest.mae != result.metrics.mae
                or manifest.mse != result.metrics.mse
                or manifest.rmse != result.metrics.rmse
                or manifest.inference_latency_ms != result.metrics.inference_latency_ms
            ):
                raise PredictionTrainingError(
                    "invalid_manifest", "training result does not match its validated manifest"
                )
            rows.append(
                (
                    manifest.model.value,
                    manifest.split_id,
                    manifest.mae,
                    manifest.rmse,
                    manifest.mse,
                    manifest.inference_latency_ms,
                    json.dumps(
                        {**manifest.as_dict(), "manifest_filename": manifest_filename},
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                )
            )
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO prediction_runs (
                    model, split_id, mae, rmse, mse, inference_latency_ms, artifact_metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def list_prediction_results(self) -> list[PersistedPredictionRun]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT model, split_id, mae, rmse, mse, inference_latency_ms,
                       artifact_metadata, created_at
                FROM prediction_runs ORDER BY id DESC
                """
            ).fetchall()
        persisted: list[PersistedPredictionRun] = []
        for row in rows:
            try:
                metadata = json.loads(row["artifact_metadata"])
                artifact_sha256 = metadata["artifact_sha256"]
                model = ModelFamily(row["model"])
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                raise PredictionTrainingError(
                    "invalid_manifest", "persisted prediction metadata is invalid"
                ) from error
            persisted.append(
                PersistedPredictionRun(
                    model=model,
                    split_id=str(row["split_id"]),
                    metrics=EvaluationMetrics(
                        mae=float(row["mae"]),
                        mse=float(row["mse"]),
                        rmse=float(row["rmse"]),
                        inference_latency_ms=float(row["inference_latency_ms"]),
                    ),
                    artifact_sha256=str(artifact_sha256),
                    artifact_metadata=metadata,
                    created_at=str(row["created_at"]),
                )
            )
        return persisted

    @staticmethod
    def _encode_seed(seed: int) -> str:
        return f"0x{seed:x}"

    @staticmethod
    def _decode_seed(value: str | int | float) -> int:
        if isinstance(value, str) and value.startswith("0x"):
            return int(value, 16)
        return int(value)
