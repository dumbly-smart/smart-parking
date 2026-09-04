# Parking Lifecycle API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver atomic, retry-safe RFID entry and exit plus a five-slot parking-status API for hardware and simulated clients.

**Architecture:** Immutable parking schemas define the public contract, a parking service builds allocation requests and owns lifecycle policy, and explicit `Database` methods own SQLite transactions. Thin FastAPI routes translate typed conflicts to stable HTTP responses.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic 2, standard-library `sqlite3`, SHA-256, pytest, Ruff

**Spec:** `docs/superpowers/specs/2026-09-04-parking-lifecycle-api-design.md`

## Global Constraints

- Version 1 has exactly five slots with IDs 1 through 5.
- Entry and exit require non-empty `rfid_uid` and `idempotency_key` values.
- Entry and exit keys share one persistent logical namespace.
- Runtime mode does not alter lifecycle behavior or response schemas.
- Only `Settings.selected_optimizer` selects entry slots.
- Occupied slots are never assignable.
- Entry and exit use `BEGIN IMMEDIATE` and return an open-gate action only after commit.
- Stored timestamps are timezone-aware UTC strings.
- Lifecycle seeds are unsigned SHA-256 prefixes stored losslessly as hexadecimal text.
- Camera, prediction, dashboard, and firmware changes are out of scope.

---

### Task 1: Parking contracts and idempotent schema migration

**Files:**
- Create: `backend/app/models/__init__.py`
- Create: `backend/app/models/parking.py`
- Modify: `backend/app/db.py`
- Create: `tests/test_parking_api.py`

**Interfaces:**
- Consumes: `Database.initialize(slots: Sequence[SlotConfig]) -> None`
- Produces: `VehicleOperationRequest`, `EntryResponse`, `ExitResponse`, `ParkingSlotStatus`, `ParkingStatusResponse`, `ParkingSlotRecord`, and `ParkingConflict`
- Produces: nullable `parking_sessions.exit_idempotency_key`, `entry_slot_name`, and `exit_slot_name` plus unique partial index `unique_exit_idempotency_key`

- [ ] **Step 1: Write failing schema and migration tests**

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

- [ ] **Step 2: Run the tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_parking_api.py -v`

Expected: collection fails because `backend.app.models.parking` does not exist.

- [ ] **Step 3: Implement immutable contracts**

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
    def normalize_uid(cls, value: str) -> str:
        return value.upper()


class ParkingConflict(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
```

Define frozen response models with constrained slot IDs. `EntryResponse`
contains `session_id`, `rfid_uid`, `slot_id`, `slot_name`, `optimizer`,
`allocation_cost`, `entered_at`, and literal `gate_action="open"`.
`ExitResponse` contains the analogous released-slot fields and `exited_at`.
`ParkingSlotStatus` contains persisted metadata plus nullable active-session
fields. Validate `ParkingStatusResponse.slots` contains IDs 1 through 5.

- [ ] **Step 4: Implement the idempotent migration**

Add `exit_idempotency_key TEXT` to fresh DDL. After `executescript(SCHEMA)`,
inspect and migrate older databases before creating the index:

```python
columns = {
    row["name"]
    for row in connection.execute("PRAGMA table_info(parking_sessions)")
}
for column in ("exit_idempotency_key", "entry_slot_name", "exit_slot_name"):
    if column not in columns:
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
```

- [ ] **Step 5: Run focused regression tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_parking_api.py tests/test_foundation.py -v`

Expected: all collected tests pass.

- [ ] **Step 6: Commit the contract slice**

```bash
git add backend/app/models backend/app/db.py tests/test_parking_api.py
git commit -m "feat: define parking lifecycle contracts"
```

---

### Task 2: Atomic entry service and endpoint

**Files:**
- Create: `backend/app/services/__init__.py`
- Create: `backend/app/services/parking.py`
- Create: `backend/app/routes/parking.py`
- Modify: `backend/app/db.py`
- Modify: `backend/app/main.py`
- Modify: `tests/test_parking_api.py`

**Interfaces:**
- Consumes: `OPTIMIZERS: dict[str, Optimizer]`, `AllocationRequest`, `SlotCandidate`, `ObjectiveWeights`
- Produces: `Database.enter_vehicle(rfid_uid: str, idempotency_key: str, allocate: Callable[[tuple[ParkingSlotRecord, ...]], AllocationResult]) -> EntryResponse`
- Produces: `ParkingService.enter(request: VehicleOperationRequest) -> EntryResponse`
- Produces: `POST /api/vehicle/entry`

- [ ] **Step 1: Write a failing successful-entry integration test**

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
```

- [ ] **Step 2: Run the entry test and verify RED**

Run: `.venv/bin/python -m pytest tests/test_parking_api.py::test_entry_allocates_free_slot_and_persists_atomically -v`

Expected: `404 Not Found` because the route is absent.

- [ ] **Step 3: Implement optimizer request construction**

```python
def _seed_for(request: VehicleOperationRequest) -> int:
    identity = f"{request.rfid_uid}:{request.idempotency_key}".encode()
    return int.from_bytes(hashlib.sha256(identity).digest()[:8], "big")


def _allocate(self, request: VehicleOperationRequest, slots: tuple[ParkingSlotRecord, ...]) -> AllocationResult:
    totals = Counter(slot.zone for slot in slots)
    occupied = Counter(slot.zone for slot in slots if slot.occupied)
    candidates = tuple(
        SlotCandidate(
            slot_id=slot.id,
            occupied=slot.occupied,
            distance=slot.walking_distance,
            congestion=occupied[slot.zone] / totals[slot.zone],
            waiting=0.0,
            fairness=0.0,
        )
        for slot in slots
    )
    return self.optimizer.optimize(
        AllocationRequest(
            scenario_id=f"entry:{hashlib.sha256(request.idempotency_key.encode()).hexdigest()}",
            candidates=candidates,
            weights=self.weights,
            seed=_seed_for(request),
            iterations=30,
        )
    )
```

Implement `Database.enter_vehicle` with `BEGIN IMMEDIATE`, cross-namespace key
lookup, active-session validation, five-slot read, callback invocation, and
inserts for optimizer run, session, allocation, and occupied-slot update. Catch
no domain errors inside the transaction so the connection context rolls back.

- [ ] **Step 4: Register the service and route, then verify GREEN**

```python
@router.post("/api/vehicle/entry", response_model=EntryResponse)
def enter_vehicle(payload: VehicleOperationRequest, request: Request) -> EntryResponse:
    try:
        return request.app.state.parking_service.enter(payload)
    except (ParkingConflict, NoAvailableSlotError) as exc:
        code = exc.code if isinstance(exc, ParkingConflict) else "no_available_slot"
        raise HTTPException(
            status_code=409,
            detail={"code": code, "message": str(exc)},
        ) from exc
```

Run: `.venv/bin/python -m pytest tests/test_parking_api.py::test_entry_allocates_free_slot_and_persists_atomically -v`

Expected: PASS.

- [ ] **Step 5: Add failing retry, conflict, capacity, safety, and rollback tests**

Add independent tests that prove:

```python
assert retry.json() == first.json()
assert table_counts(settings) == first_counts
assert active_again.json()["detail"]["code"] == "vehicle_already_parked"
assert full.json()["detail"]["code"] == "no_available_slot"
assert chosen_slot_id not in preoccupied_slot_ids
assert table_counts(settings) == counts_before_injected_trigger_failure
```

Use a real SQLite trigger that aborts allocation insertion for the rollback
case. For capacity and occupied safety, update `parking_slots` in the temporary
database before posting.

Add boundary tests for 122-, 123-, and 128-character keys, a known unsigned
SHA-256 seed vector, and restart-based entry/exit replay after slot renaming.

- [ ] **Step 6: Run the new tests and verify RED, then complete entry branches**

Run: `.venv/bin/python -m pytest tests/test_parking_api.py -k 'entry or capacity or rollback' -v`

Expected before implementation: failures for missing replay and conflict
branches. Add exact key-identity queries and replay reconstruction, then rerun
until all selected tests pass.

- [ ] **Step 7: Commit the entry slice**

```bash
git add backend/app/services backend/app/routes/parking.py backend/app/db.py backend/app/main.py tests/test_parking_api.py
git commit -m "feat: add atomic vehicle entry"
```

---

### Task 3: Atomic exit and parking status

**Files:**
- Modify: `backend/app/db.py`
- Modify: `backend/app/services/parking.py`
- Modify: `backend/app/routes/parking.py`
- Modify: `tests/test_parking_api.py`

**Interfaces:**
- Produces: `Database.exit_vehicle(rfid_uid: str, idempotency_key: str) -> ExitResponse`
- Produces: `Database.parking_status() -> ParkingStatusResponse`
- Produces: `ParkingService.exit(...)`, `ParkingService.status()`
- Produces: `POST /api/vehicle/exit`, `GET /api/parking/status`

- [ ] **Step 1: Write failing exit lifecycle and replay tests**

```python
def test_exit_closes_session_and_frees_slot(tmp_path: Path) -> None:
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
    assert replay.json() == exited.json()
```

Add separate tests for `vehicle_not_parked`, cross-operation key reuse,
cross-vehicle key reuse, and preservation of the original exit timestamp.

- [ ] **Step 2: Run exit tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_parking_api.py -k 'exit or idempotency_conflict' -v`

Expected: `404 Not Found` for the exit endpoint.

- [ ] **Step 3: Implement exit transaction and endpoint**

```python
@router.post("/api/vehicle/exit", response_model=ExitResponse)
def exit_vehicle(payload: VehicleOperationRequest, request: Request) -> ExitResponse:
    try:
        return request.app.state.parking_service.exit(payload)
    except ParkingConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
```

Within `Database.exit_vehicle`, reserve the transaction, validate the shared
key namespace, replay an identical stored exit, select the active session,
write one UTC exit timestamp and key, free the slot using the same timestamp,
and return the committed values.

- [ ] **Step 4: Write failing status and concurrent-entry tests**

```python
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
    assert active["rfid_uid"] == "CARD-1"
```

The concurrency test submits distinct RFID operations through two threads and
asserts both successful responses have different slot IDs and two active
sessions exist.

- [ ] **Step 5: Implement status query and verify GREEN**

Use a left join from `parking_slots` through active `parking_sessions` and
`vehicles`, ordered by slot ID. Expose it through:

```python
@router.get("/api/parking/status", response_model=ParkingStatusResponse)
def parking_status(request: Request) -> ParkingStatusResponse:
    return request.app.state.parking_service.status()
```

Run: `.venv/bin/python -m pytest tests/test_parking_api.py -v`

Expected: all parking lifecycle tests pass.

- [ ] **Step 6: Commit exit and status**

```bash
git add backend/app/db.py backend/app/services/parking.py backend/app/routes/parking.py tests/test_parking_api.py
git commit -m "feat: add vehicle exit and parking status"
```

---

### Task 4: Public documentation, decisions, and milestone verification

**Files:**
- Modify: `README.md`
- Modify: `decisions.md`
- Modify: `progress.md`

**Interfaces:**
- Documents: request/response examples for all three public endpoints
- Records: persistent shared idempotency namespace and `BEGIN IMMEDIATE` transaction boundary
- Advances: Milestone 3 to complete and vision occupancy to next task

- [ ] **Step 1: Add README API examples**

Document curl examples using these exact payloads:

```bash
curl -X POST http://127.0.0.1:8000/api/vehicle/entry \
  -H 'Content-Type: application/json' \
  -d '{"rfid_uid":"04-A1-B2-C3","idempotency_key":"entry-0001"}'

curl -X POST http://127.0.0.1:8000/api/vehicle/exit \
  -H 'Content-Type: application/json' \
  -d '{"rfid_uid":"04-A1-B2-C3","idempotency_key":"exit-0001"}'

curl http://127.0.0.1:8000/api/parking/status
```

- [ ] **Step 2: Append ADR-009**

Record that entry and exit keys share one persisted namespace, lifecycle
transactions use `BEGIN IMMEDIATE`, and responses commanding the gate open are
returned only after successful commit.

- [ ] **Step 3: Run complete verification**

Run:

```bash
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
git diff --check
```

Expected: every test passes, Ruff reports no errors, and the diff check is
silent.

- [ ] **Step 4: Update progress with fresh evidence**

Set Parking lifecycle API to complete, record exact test counts and commands,
active branch and latest implementation commit, and name the occupancy
heuristic/ROI camera update flow as the next concrete task.

- [ ] **Step 5: Review and commit documentation**

```bash
git add README.md decisions.md progress.md
git diff --cached --check
git diff --cached
git commit -m "docs: complete parking lifecycle milestone"
git show --stat --oneline HEAD
git status --short --branch
```
