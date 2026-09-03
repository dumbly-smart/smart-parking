# Demo Entry/Exit API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an atomic, retry-safe demo RFID entry/exit lifecycle and five-slot parking-status API.

**Architecture:** A typed parking service builds optimizer requests and owns lifecycle policy, while explicit `Database` transaction methods own SQLite reads and writes. Thin FastAPI routes validate input and translate typed domain conflicts to structured HTTP 409 responses.

**Tech Stack:** Python 3.11, FastAPI, Pydantic v2, standard-library `sqlite3`, pytest, Ruff

**Spec:** `docs/superpowers/specs/2026-09-03-demo-entry-exit-api-design.md`

## Global Constraints

- The system has exactly five slots, with IDs 1 through 5.
- Entry and exit requests require a non-empty RFID UID and idempotency key.
- Entry and exit keys share one logical namespace and persist across restarts.
- Only the optimizer named by `Settings.selected_optimizer` may select an entry slot.
- Occupied slots must never be assigned.
- Entry and exit persistence must each be atomic under `BEGIN IMMEDIATE`.
- Successful gate actions are returned only after the transaction commits.
- Camera occupancy, prediction, dashboard, and firmware work remain out of scope.

---

### Task 1: Parking Models and Schema Migration

**Files:**
- Create: `backend/app/models/__init__.py`
- Create: `backend/app/models/parking.py`
- Modify: `backend/app/db.py`
- Test: `tests/test_parking_api.py`

**Interfaces:**
- Produces: `VehicleOperationRequest`, `EntryResponse`, `ExitResponse`, `ParkingSlotStatus`, `ParkingStatusResponse`, `ParkingConflict`, and immutable internal `ParkingSlotRecord`.
- Produces: an idempotent `parking_sessions.exit_idempotency_key` migration with a unique partial index.
- Consumes: `Database.initialize(slots: Sequence[SlotConfig]) -> None`.

- [ ] **Step 1: Add failing request-normalization and migration tests**

Create the test module and shared application helper. Assert whitespace trimming,
uppercased RFID UIDs, rejected blank strings, and initialization of both fresh
and legacy databases:

```python
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
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_parking_api.py -v`

Expected: collection fails because `backend.app.models.parking` does not exist.

- [ ] **Step 3: Add immutable parking models**

Implement the public and internal schemas, using a shared validator so the
wire contract is unambiguous:

```python
class VehicleOperationRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    rfid_uid: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=128)

    @field_validator("rfid_uid", "idempotency_key", mode="before")
    @classmethod
    def strip_identifier(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("rfid_uid")
    @classmethod
    def normalize_rfid_uid(cls, value: str) -> str:
        return value.upper()


class EntryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    session_id: int
    rfid_uid: str
    slot_id: int = Field(ge=1, le=5)
    slot_name: str
    optimizer: Literal["ga", "pso", "aco"]
    allocation_cost: float = Field(ge=0, le=1)
    entered_at: str
    gate_action: Literal["open"] = "open"
```

Define `ExitResponse` with `session_id: int`, `rfid_uid: str`, constrained
`slot_id: int`, `slot_name: str`, `exited_at: str`, and literal
`gate_action: "open"`. Define `ParkingSlotStatus` with `id`, `name`,
`walking_distance`, `zone`, `occupied`, `updated_at`, nullable
`active_session_id`, and nullable `rfid_uid`; wrap exactly five of them in
`ParkingStatusResponse.slots`. Define `ParkingSlotRecord` with `id`, `name`,
`walking_distance`, `zone`, `occupied`, and `updated_at`. Define
`ParkingConflict(RuntimeError)` with stable `code` and `message` attributes.

- [ ] **Step 4: Implement the idempotent schema migration**

Add `exit_idempotency_key TEXT` to the fresh-table DDL. After
`connection.executescript(SCHEMA)`, inspect `PRAGMA table_info` and migrate old
databases before creating the partial unique index:

```python
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
```

- [ ] **Step 5: Run focused and regression tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_parking_api.py tests/test_foundation.py -v`

Expected: all collected tests pass.

- [ ] **Step 6: Commit the model and migration slice**

```bash
git add backend/app/models tests/test_parking_api.py backend/app/db.py
git commit -m "feat: define parking lifecycle contracts"
```

---

### Task 2: Atomic Entry Service and Endpoint

**Files:**
- Create: `backend/app/services/__init__.py`
- Create: `backend/app/services/parking.py`
- Create: `backend/app/routes/parking.py`
- Modify: `backend/app/db.py`
- Modify: `backend/app/main.py`
- Test: `tests/test_parking_api.py`

**Interfaces:**
- Consumes: `VehicleOperationRequest`, `EntryResponse`, `ParkingSlotRecord`, `ParkingConflict`.
- Consumes: `OPTIMIZERS: dict[str, Optimizer]`, `AllocationRequest`, `SlotCandidate`, `ObjectiveWeights`.
- Produces: `Database.enter_vehicle(rfid_uid: str, idempotency_key: str, allocate: Callable[[tuple[ParkingSlotRecord, ...]], AllocationResult]) -> EntryResponse`.
- Produces: `ParkingService.enter(request: VehicleOperationRequest) -> EntryResponse`.
- Produces: `POST /api/vehicle/entry`.

- [ ] **Step 1: Add a failing successful-entry integration test**

Post a real request, then inspect all persistence side effects:

```python
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
        assert connection.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM parking_sessions").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM allocations").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM optimizer_runs").fetchone()[0] == 1
        occupied = connection.execute(
            "SELECT occupied FROM parking_slots WHERE id = ?", (body["slot_id"],)
        ).fetchone()[0]
    assert occupied == 1
```

- [ ] **Step 2: Run the entry test and verify RED**

Run: `.venv/bin/python -m pytest tests/test_parking_api.py::test_entry_allocates_free_slot_and_persists_atomically -v`

Expected: `404 Not Found` for the missing route.

- [ ] **Step 3: Implement entry transaction and optimizer request construction**

In `Database.enter_vehicle`, execute `BEGIN IMMEDIATE`, query both entry and
exit key columns before any inserts, then query active vehicle sessions. Pass
five immutable `ParkingSlotRecord` values to `allocate`. Persist the returned
optimizer result, session, allocation, and slot update before constructing the
typed response. Use the inserted optimizer row ID for `allocations.optimizer_run_id`.

In `ParkingService`, inject `Database`, selected optimizer name, and weights.
Build candidates as follows:

```python
def allocate(slots: tuple[ParkingSlotRecord, ...]) -> AllocationResult:
    zone_totals = Counter(slot.zone for slot in slots)
    zone_occupied = Counter(slot.zone for slot in slots if slot.occupied)
    candidates = tuple(
        SlotCandidate(
            slot_id=slot.id,
            occupied=slot.occupied,
            distance=slot.walking_distance,
            congestion=zone_occupied[slot.zone] / zone_totals[slot.zone],
            waiting=0.0,
            fairness=0.0,
        )
        for slot in slots
    )
    return self.optimizer.optimize(
        AllocationRequest(
            scenario_id=f"entry:{request.idempotency_key}",
            candidates=candidates,
            weights=self.weights,
            seed=42,
            iterations=30,
        )
    )
```

Register a `ParkingService` during lifespan startup and include the new router.
The route returns `EntryResponse` and translates `ParkingConflict` and
`NoAvailableSlotError` into the structured 409 detail contract.

- [ ] **Step 4: Run the successful-entry test and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_parking_api.py::test_entry_allocates_free_slot_and_persists_atomically -v`

Expected: PASS.

- [ ] **Step 5: Add failing entry retry, active-vehicle, capacity, occupied-safety, and rollback tests**

Add separate tests that:

```python
first = client.post("/api/vehicle/entry", json=payload)
retry = client.post("/api/vehicle/entry", json=payload)
assert retry.json() == first.json()
assert table_counts(settings.database_path) == {
    "vehicles": 1, "parking_sessions": 1, "allocations": 1, "optimizer_runs": 1
}
```

Also assert a new key for `CARD-1` returns `vehicle_already_parked`; manually
occupy slots 1-4 and assert slot 5 is chosen; occupy all five and assert
`no_available_slot` with zero vehicle/session/allocation/optimizer rows. Add a
trigger that aborts allocation insertion and assert the HTTP call raises under
a client created as `TestClient(create_app(settings),
raise_server_exceptions=True)` while every earlier write is rolled back.

- [ ] **Step 6: Run the new entry tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_parking_api.py -k 'entry or capacity or occupied or rollback' -v`

Expected: retry/conflict/safety tests fail until their branches are complete.

- [ ] **Step 7: Complete entry replay and conflict handling minimally**

On a matching entry key, join `allocations`, `parking_sessions`, `vehicles`,
`parking_slots`, and `optimizer_runs` to reconstruct the original
`EntryResponse`. On a nonmatching UID or a key found in
`parking_sessions.exit_idempotency_key`, raise:

```python
raise ParkingConflict(
    code="idempotency_conflict",
    message="idempotency key is already used by another operation",
)
```

Raise `vehicle_already_parked` before optimizer invocation when the normalized
UID has an active session. Allow `NoAvailableSlotError` to escape the database
method so the context manager rolls back the vehicle upsert.

- [ ] **Step 8: Run entry tests and the full suite and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_parking_api.py -k 'entry or capacity or occupied or rollback' -v`

Run: `.venv/bin/python -m pytest`

Expected: all tests pass.

- [ ] **Step 9: Commit the atomic entry slice**

```bash
git add backend/app/db.py backend/app/main.py backend/app/routes/parking.py backend/app/services tests/test_parking_api.py
git commit -m "feat: add atomic idempotent vehicle entry"
```

---

### Task 3: Atomic Exit and Shared Idempotency Namespace

**Files:**
- Modify: `backend/app/db.py`
- Modify: `backend/app/services/parking.py`
- Modify: `backend/app/routes/parking.py`
- Test: `tests/test_parking_api.py`

**Interfaces:**
- Consumes: `VehicleOperationRequest`, `ExitResponse`, `ParkingConflict`.
- Produces: `Database.exit_vehicle(rfid_uid: str, idempotency_key: str) -> ExitResponse`.
- Produces: `ParkingService.exit(request: VehicleOperationRequest) -> ExitResponse`.
- Produces: `POST /api/vehicle/exit`.

- [ ] **Step 1: Add a failing successful-exit test**

Enter a vehicle through the API, exit it, and verify the response and state:

```python
exit_response = client.post(
    "/api/vehicle/exit",
    json={"rfid_uid": "card-1", "idempotency_key": "exit-1"},
)
assert exit_response.status_code == 200
assert exit_response.json()["gate_action"] == "open"
assert exit_response.json()["slot_id"] == entry_response.json()["slot_id"]
with sqlite3.connect(settings.database_path) as connection:
    session = connection.execute(
        "SELECT exited_at, exit_idempotency_key FROM parking_sessions"
    ).fetchone()
    occupied = connection.execute(
        "SELECT occupied FROM parking_slots WHERE id = ?",
        (exit_response.json()["slot_id"],),
    ).fetchone()[0]
assert session[0] is not None
assert session[1] == "exit-1"
assert occupied == 0
```

- [ ] **Step 2: Run the exit test and verify RED**

Run: `.venv/bin/python -m pytest tests/test_parking_api.py::test_exit_closes_session_and_frees_slot -v`

Expected: `404 Not Found` for the missing route.

- [ ] **Step 3: Implement the atomic exit flow**

Under `BEGIN IMMEDIATE`, check whether the exit key already identifies a
session. For an identical UID, reconstruct and return the stored response. For
a different UID or a key present in the entry namespace, raise
`idempotency_conflict`. Otherwise find the UID's active session, calculate one
UTC timestamp in SQLite, update `exited_at` and `exit_idempotency_key`, and mark
the same slot free before commit.

Add the service passthrough and typed exit route with the same structured
conflict translator used by entry.

- [ ] **Step 4: Run the successful-exit test and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_parking_api.py::test_exit_closes_session_and_frees_slot -v`

Expected: PASS.

- [ ] **Step 5: Add failing exit retry and conflict tests**

Assert an identical exit retry returns the exact original response and does not
change row counts or `exited_at`. Assert exit for an unknown or already-exited
UID returns `vehicle_not_parked`. Parameterize these shared-namespace cases:

```python
@pytest.mark.parametrize(
    ("first_path", "second_path"),
    [
        ("/api/vehicle/entry", "/api/vehicle/exit"),
        ("/api/vehicle/exit", "/api/vehicle/entry"),
    ],
)
def test_idempotency_key_cannot_cross_operation_namespaces(
    tmp_path: Path, first_path: str, second_path: str
) -> None:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        client.post(
            "/api/vehicle/entry",
            json={"rfid_uid": "CARD-1", "idempotency_key": "entry-setup"},
        )
        shared_key = "shared-operation-key"
        if first_path.endswith("exit"):
            first_uid = "CARD-1"
            client.post(
                first_path,
                json={"rfid_uid": first_uid, "idempotency_key": shared_key},
            )
        else:
            client.post(
                "/api/vehicle/exit",
                json={"rfid_uid": "CARD-1", "idempotency_key": "exit-setup"},
            )
            first_uid = "CARD-2"
            client.post(
                first_path,
                json={"rfid_uid": first_uid, "idempotency_key": shared_key},
            )
        response = client.post(
            second_path,
            json={"rfid_uid": first_uid, "idempotency_key": shared_key},
        )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "idempotency_conflict"
```

For the exit-first case, create and exit a session with one key, then attempt a
new entry with that exit key. Add a cross-vehicle case using one entry key for
two UIDs. Every conflict must leave slot and session state unchanged.

- [ ] **Step 6: Run conflict tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_parking_api.py -k 'exit or idempotency' -v`

Expected: the new replay/conflict assertions fail until all checks are present.

- [ ] **Step 7: Complete replay and shared-key conflict handling**

Centralize key lookups in small private database helpers accepting the active
connection. Ensure key-type checks happen before active-session checks so the
same key always yields `idempotency_conflict`, independent of current vehicle
state.

- [ ] **Step 8: Run focused and full tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_parking_api.py -k 'exit or idempotency' -v`

Run: `.venv/bin/python -m pytest`

Expected: all tests pass.

- [ ] **Step 9: Commit the exit slice**

```bash
git add backend/app/db.py backend/app/routes/parking.py backend/app/services/parking.py tests/test_parking_api.py
git commit -m "feat: add atomic idempotent vehicle exit"
```

---

### Task 4: Five-Slot Parking Status API

**Files:**
- Modify: `backend/app/db.py`
- Modify: `backend/app/services/parking.py`
- Modify: `backend/app/routes/parking.py`
- Test: `tests/test_parking_api.py`

**Interfaces:**
- Produces: `Database.parking_status() -> ParkingStatusResponse`.
- Produces: `ParkingService.status() -> ParkingStatusResponse`.
- Produces: `GET /api/parking/status`.

- [ ] **Step 1: Add a failing parking-status integration test**

Assert empty status, then enter one vehicle and assert the active join:

```python
response = client.get("/api/parking/status")
assert response.status_code == 200
assert [slot["id"] for slot in response.json()["slots"]] == [1, 2, 3, 4, 5]
assert all(slot["active_session_id"] is None for slot in response.json()["slots"])

entry = client.post("/api/vehicle/entry", json=entry_payload).json()
status = client.get("/api/parking/status").json()["slots"]
assigned = next(slot for slot in status if slot["id"] == entry["slot_id"])
assert assigned["occupied"] is True
assert assigned["active_session_id"] == entry["session_id"]
assert assigned["rfid_uid"] == "CARD-1"
```

- [ ] **Step 2: Run the status test and verify RED**

Run: `.venv/bin/python -m pytest tests/test_parking_api.py::test_status_returns_ordered_slots_and_active_session -v`

Expected: `404 Not Found` for the missing route.

- [ ] **Step 3: Implement the typed status query and endpoint**

Use a `LEFT JOIN` from all `parking_slots` to only active
`parking_sessions`, then to `vehicles`, ordered by slot ID. Validate each row as
`ParkingSlotStatus` and return `ParkingStatusResponse(slots=tuple(statuses))`.
Add the service passthrough and `response_model=ParkingStatusResponse` route.

- [ ] **Step 4: Run focused and full tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_parking_api.py::test_status_returns_ordered_slots_and_active_session -v`

Run: `.venv/bin/python -m pytest`

Expected: all tests pass.

- [ ] **Step 5: Commit the status slice**

```bash
git add backend/app/db.py backend/app/routes/parking.py backend/app/services/parking.py tests/test_parking_api.py
git commit -m "feat: expose five-slot parking status"
```

---

### Task 5: Public Documentation, Decision Record, and Milestone Verification

**Files:**
- Modify: `README.md`
- Modify: `decisions.md`
- Modify: `progress.md`

**Interfaces:**
- Documents: exact entry, exit, status requests and structured conflicts.
- Records: atomic SQLite lifecycle and shared idempotency namespace decision.
- Updates: Milestone 3 evidence and next task.

- [ ] **Step 1: Add README examples for all three endpoints**

Document runnable `curl` examples using the approved JSON fields. Explain that
keys are required per operation, retries with identical payloads replay the
original result, and new visits require new keys.

- [ ] **Step 2: Append the architecture decision**

Add `ADR-009: Atomic persisted RFID lifecycle idempotency` with the accepted
decision: `BEGIN IMMEDIATE`, database-backed entry/exit replay, one logical key
namespace, and structured 409 conflicts.

- [ ] **Step 3: Run final verification before updating progress**

Run:

```bash
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
git diff --check
```

Expected: the complete suite passes, Ruff reports no errors, and diff check is
silent.

- [ ] **Step 4: Update progress with observed evidence**

Mark Demo entry/exit API complete only with the actual passing-test count from
Step 3. Summarize entry, retry, exit, capacity, and occupied-slot safety. Set
the next task to the vision occupancy pipeline contract and failing tests.

- [ ] **Step 5: Re-run documentation-sensitive checks**

Run:

```bash
.venv/bin/python -m ruff check .
git diff --check
git status --short
```

Expected: Ruff passes, diff check is silent, and status lists only intended
Milestone 3 files.

- [ ] **Step 6: Commit the completed milestone documentation**

```bash
git add README.md decisions.md progress.md
git commit -m "docs: complete demo parking lifecycle milestone"
```

- [ ] **Step 7: Verify the committed tree**

Run:

```bash
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
git diff --check
git status --short
```

Expected: all tests pass, Ruff passes, diff check is silent, and the worktree is
clean.
