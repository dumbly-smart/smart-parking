# Scalable Vision Occupancy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing backend cardinality-independent and add a deterministic, smoothed JPEG-to-occupancy API for every configured slot.

**Architecture:** Configuration defines a non-empty slot set and a matching ordered ROI set. A replaceable detector produces immutable observations, an occupancy service applies confidence and consecutive-frame policy, and SQLite atomically persists only accepted safe transitions. The existing lifecycle and all three optimizers consume the same dynamic slot set.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic Settings, sqlite3, Pillow, NumPy, pytest, Ruff

**Spec:** `docs/superpowers/specs/2026-09-04-scalable-vision-occupancy-design.md`

## Global Constraints

- The committed demo remains configured with five slots, but backend behavior must support any non-empty uniquely identified slot set.
- Slot IDs are positive and unique; they do not need to be contiguous.
- ROI mappings must match configured slot IDs exactly and responses follow parking configuration order.
- The heuristic uses Pillow `FIND_EDGES`, counts pixels with intensity at least 128, and applies the confidence formula in the spec.
- The upload limit defaults to 5 MiB and is configurable with `SMART_PARKING_CAMERA_MAX_IMAGE_BYTES`.
- Three consecutive confident frames are required by the committed ROI example.
- Vision must not free a slot with an active parking session.
- Store timezone-aware UTC timestamps and persist all accepted changes for a frame atomically.
- Preserve deterministic seeds and identical candidate inputs across GA, PSO, and ACO.
- Do not add TensorFlow, camera polling, dashboard, prediction, or firmware behavior.

---

### Task 1: Remove Fixed Slot Cardinality from Typed Contracts

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/models/parking.py`
- Modify: `backend/app/main.py`
- Modify: `optimization/models.py`
- Modify: `tests/test_foundation.py`
- Modify: `tests/test_optimization.py`
- Modify: `tests/test_parking_api.py`

**Interfaces:**
- Produces: `ParkingConfig.slots: list[SlotConfig]` with one or more unique positive IDs/names.
- Produces: `AllocationRequest.candidates: tuple[SlotCandidate, ...]` with one or more unique positive slot IDs.
- Produces: parking and allocation response models whose slot IDs are any positive integer.
- Produces: health status based on `database.slot_count() == len(settings.parking.slots)`.

- [ ] **Step 1: Write failing dynamic-cardinality tests**

Add tests equivalent to:

```python
@pytest.mark.parametrize("slot_ids", [[7], [2, 4, 9, 12, 20, 31]])
def test_settings_accepts_non_empty_unique_positive_slot_ids(
    tmp_path: Path, slot_ids: list[int]
) -> None:
    settings = make_settings_for_ids(tmp_path, slot_ids)
    assert [slot.id for slot in settings.parking.slots] == slot_ids


def test_allocation_request_accepts_dynamic_non_contiguous_candidates() -> None:
    allocation_request = AllocationRequest(
        scenario_id="dynamic",
        candidates=[candidate(2), candidate(9), candidate(21)],
    )
    assert [item.slot_id for item in allocation_request.candidates] == [2, 9, 21]


@pytest.mark.parametrize("slot_ids", [[], [1, 1], [0]])
def test_dynamic_slot_contract_rejects_invalid_sets(slot_ids: list[int]) -> None:
    with pytest.raises(ValidationError):
        build_config_or_request(slot_ids)
```

Also change the status test to use non-contiguous configured IDs and assert its
response contains exactly those IDs. Add a health test where the database count
differs from the configured count and assert `status == "degraded"`.

- [ ] **Step 2: Run tests to verify the fixed-size assumptions fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_foundation.py tests/test_optimization.py tests/test_parking_api.py -q
```

Expected: new one-slot, six-slot, or non-contiguous cases fail validation or
report degraded health using the old fixed value.

- [ ] **Step 3: Implement dynamic validation**

Use positive IDs and explicit non-empty/uniqueness checks:

```python
class SlotConfig(BaseModel):
    id: int = Field(ge=1)


@field_validator("slots")
@classmethod
def non_empty_unique_slots(cls, slots: list[SlotConfig]) -> list[SlotConfig]:
    if not slots:
        raise ValueError("at least one parking slot is required")
    if len({slot.id for slot in slots}) != len(slots):
        raise ValueError("parking slot ids must be unique")
    if len({slot.name for slot in slots}) != len(slots):
        raise ValueError("parking slot names must be unique")
    return slots
```

Apply `Field(ge=1)` to every parking/allocation slot ID. Validate allocation
candidates as non-empty with unique IDs while preserving tuple order. Replace
the fixed-five `ParkingStatusResponse` validator with a non-empty unique-ID
validator. In `/health`, compare the persisted count to the configured count.

- [ ] **Step 4: Run the focused tests**

```bash
.venv/bin/python -m pytest tests/test_foundation.py tests/test_optimization.py tests/test_parking_api.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit the contract change**

```bash
git add backend/app/config.py backend/app/models/parking.py backend/app/main.py optimization/models.py tests/test_foundation.py tests/test_optimization.py tests/test_parking_api.py
git commit -m "refactor: support configurable slot cardinality"
```

---

### Task 2: Migrate and Seed Dynamic Slot Persistence

**Files:**
- Modify: `backend/app/db.py`
- Modify: `tests/test_foundation.py`
- Modify: `tests/test_parking_api.py`

**Interfaces:**
- Consumes: dynamic `Sequence[SlotConfig]` from Task 1.
- Produces: `Database.initialize(slots: Sequence[SlotConfig]) -> None` supporting arbitrary positive IDs.
- Produces: `Database.parking_status()` ordered by configured slot order, supplied to `Database` at initialization or via explicit ordered IDs.

- [ ] **Step 1: Write failing migration and seed tests**

Create a legacy database using the current schema, seed IDs 1 through 5 and a
referencing occupancy event, initialize with configured IDs including 8, then
assert all rows and foreign keys survive and ID 8 can be inserted. Add tests
for fresh non-contiguous initialization, idempotent reinitialization, and
rejection when an existing database contains a slot absent from configuration:

```python
with sqlite3.connect(settings.database_path) as connection:
    sql = connection.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'parking_slots'"
    ).fetchone()[0]
    event = connection.execute(
        "SELECT slot_id, occupied FROM occupancy_events"
    ).fetchone()
assert "BETWEEN 1 AND 5" not in sql
assert event == (1, 1)
assert database.slot_count() == 6
```

- [ ] **Step 2: Run migration tests to verify failure**

```bash
.venv/bin/python -m pytest tests/test_foundation.py -k "dynamic or migrate" -q
```

Expected: FAIL because `parking_slots` still has the upper-bound check and
`initialize` still requires five slots.

- [ ] **Step 3: Implement the transactional migration**

Split the schema so new databases create:

```sql
CREATE TABLE IF NOT EXISTS parking_slots (
    id INTEGER PRIMARY KEY CHECK (id >= 1),
    name TEXT NOT NULL UNIQUE,
    walking_distance REAL NOT NULL CHECK (walking_distance BETWEEN 0 AND 1),
    zone TEXT NOT NULL,
    occupied INTEGER NOT NULL DEFAULT 0 CHECK (occupied IN (0, 1)),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
```

Before running dependent DDL, inspect `sqlite_master.sql`. If it contains the
legacy check, run a transaction-safe rebuild that disables foreign-key checks
before the transaction, creates `parking_slots_new`, copies all columns,
replaces the table, recreates indexes, and finishes with
`PRAGMA foreign_key_check`. Restore foreign-key enforcement in `finally`.
After migration, reject empty configuration and any persisted ID not present in
the configured ID set, then upsert every configured slot.

Preserve canonical YAML order by storing `self._slot_order` on `Database`
during initialization and ordering status rows with a generated `CASE s.id`
expression using bound ID parameters.

- [ ] **Step 4: Run persistence and lifecycle tests**

```bash
.venv/bin/python -m pytest tests/test_foundation.py tests/test_parking_api.py -q
```

Expected: PASS, including legacy migration and non-contiguous lifecycle cases.

- [ ] **Step 5: Commit the migration**

```bash
git add backend/app/db.py tests/test_foundation.py tests/test_parking_api.py
git commit -m "feat: migrate persistence for dynamic slots"
```

---

### Task 3: Add ROI Configuration and Deterministic Detection

**Files:**
- Create: `vision/__init__.py`
- Create: `vision/models.py`
- Create: `vision/detector.py`
- Create: `config/rois.example.json`
- Create: `tests/test_occupancy_detector.py`
- Modify: `backend/app/config.py`
- Modify: `.env.example`

**Interfaces:**
- Produces: `RoiConfig`, `RoiRegion`, and `HeuristicConfig` immutable Pydantic models.
- Produces: `DetectorObservation(slot_id: int, candidate_occupied: bool, score: float, confidence: float)`.
- Produces: `HeuristicDetector.detect(image_bytes: bytes) -> tuple[DetectorObservation, ...]`.
- Produces: `VisionInputError(code: str, message: str)` with `empty_image`, `image_too_large`, `invalid_image`, or `roi_out_of_bounds`.

- [ ] **Step 1: Write failing ROI and detector tests**

Generate images in memory with Pillow and test exact scores:

```python
def jpeg_bytes(image: Image.Image) -> bytes:
    stream = BytesIO()
    image.save(stream, format="JPEG", quality=100, subsampling=0)
    return stream.getvalue()


def test_detector_returns_configured_slot_order() -> None:
    observations = detector_for_slots([9, 2]).detect(jpeg_bytes(test_frame()))
    assert [item.slot_id for item in observations] == [9, 2]


def test_roi_config_must_match_parking_slots_exactly(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="ROI slot ids must match"):
        settings_with_roi_ids(tmp_path, parking_ids=[2, 9], roi_ids=[2])
```

Add cases for a uniform free crop, patterned occupied crop, confidence at both
extremes, non-JPEG bytes, an empty payload, oversized bytes, and an ROI extending
one pixel beyond the decoded image.

- [ ] **Step 2: Run detector tests to verify imports fail**

```bash
.venv/bin/python -m pytest tests/test_occupancy_detector.py -q
```

Expected: FAIL because the vision models and detector do not exist.

- [ ] **Step 3: Implement ROI models and Settings loading**

Define frozen models:

```python
class HeuristicConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    edge_threshold: float = Field(gt=0, lt=1)
    minimum_confidence: float = Field(ge=0, le=1)
    required_consecutive_frames: int = Field(ge=1)


class RoiRegion(BaseModel):
    model_config = ConfigDict(frozen=True)
    slot_id: int = Field(ge=1)
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
```

Load JSON in `Settings.__init__`, validate unique ROI IDs, compare them with the
parking ID set, and retain ROI order aligned to parking configuration. Default
`roi_config_path` to `config/rois.example.json`; add
`camera_max_image_bytes: int = Field(default=5 * 1024 * 1024, gt=0)`.

- [ ] **Step 4: Implement image decoding and heuristic scoring**

Use `Image.open(BytesIO(payload))`, call `verify`, reopen, require
`image.format == "JPEG"`, convert to `L`, validate every rectangle, crop, and
apply `ImageFilter.FIND_EDGES`. Compute:

```python
pixels = np.asarray(edges, dtype=np.uint8)
score = float(np.count_nonzero(pixels >= 128) / pixels.size)
occupied = score >= threshold
confidence = (
    (score - threshold) / (1.0 - threshold)
    if occupied
    else 1.0 - score / threshold
)
confidence = min(max(confidence, 0.0), 1.0)
```

Return observations in configured parking order and raise `VisionInputError`
before returning partial results.

- [ ] **Step 5: Run detector and configuration tests**

```bash
.venv/bin/python -m pytest tests/test_occupancy_detector.py tests/test_foundation.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit detector support**

```bash
git add vision config/rois.example.json backend/app/config.py .env.example tests/test_occupancy_detector.py tests/test_foundation.py
git commit -m "feat: add configurable occupancy detector"
```

---

### Task 4: Add Smoothing and Atomic Occupancy Persistence

**Files:**
- Create: `backend/app/models/occupancy.py`
- Create: `backend/app/services/occupancy.py`
- Create: `tests/test_occupancy_service.py`
- Modify: `backend/app/db.py`

**Interfaces:**
- Consumes: `tuple[DetectorObservation, ...]` from Task 3.
- Produces: `OccupancyService.process(image_bytes: bytes) -> OccupancyUpdateResponse`.
- Produces: `Database.apply_occupancy_transitions(transitions: Sequence[OccupancyTransition], observed_at: str) -> frozenset[int]`, returning slot IDs blocked by active sessions.
- Produces: immutable `SlotOccupancyResult` and `OccupancyUpdateResponse` API-ready models.

- [ ] **Step 1: Write failing smoothing tests with a fake detector**

Use a fake detector returning controlled observations and assert:

```python
first = service.process(b"frame-1")
second = service.process(b"frame-2")
third = service.process(b"frame-3")

assert [first.slots[0].outcome, second.slots[0].outcome] == ["pending", "pending"]
assert third.slots[0].outcome == "accepted"
assert third.slots[0].accepted_occupied is True
```

Add independent two-slot streaks, uncertain reset, unchanged reset, restart
reset, blocked-free transition with an active session, one event per accepted
change, and injected event-insert failure rolling back both slot and event rows.

- [ ] **Step 2: Run service tests to verify failure**

```bash
.venv/bin/python -m pytest tests/test_occupancy_service.py -q
```

Expected: FAIL because occupancy models, service, and database method do not
exist.

- [ ] **Step 3: Implement typed results and per-slot smoothing**

Define:

```python
class SlotOccupancyResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    slot_id: int = Field(ge=1)
    candidate_occupied: bool
    accepted_occupied: bool
    score: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    outcome: Literal["unchanged", "pending", "accepted", "blocked"]
    consecutive_frames: int = Field(ge=0)


class OccupancyUpdateResponse(BaseModel):
    model_config = ConfigDict(frozen=True)
    detector: Literal["heuristic"] = "heuristic"
    observed_at: str
    slots: tuple[SlotOccupancyResult, ...]
```

Track pending state in `dict[int, PendingState]`. Build proposed transitions
without mutating that dictionary, call the database once, and update pending
state only after a successful commit. Use one UTC timestamp ending in `Z` for
the complete frame.

- [ ] **Step 4: Implement the reserved database transaction**

Within `BEGIN IMMEDIATE`, read every target slot and its active-session flag.
For a requested free transition with an active session, add the ID to the
blocked set. For every other actual change, execute:

```sql
UPDATE parking_slots
SET occupied = ?, updated_at = ?
WHERE id = ? AND occupied = ?;

INSERT INTO occupancy_events
    (slot_id, occupied, confidence, source, observed_at)
VALUES (?, ?, ?, 'camera_heuristic', ?);
```

Require the update row count to be one and raise on unknown or concurrently
changed slots so the full transaction rolls back.

- [ ] **Step 5: Run service, lifecycle, and persistence tests**

```bash
.venv/bin/python -m pytest tests/test_occupancy_service.py tests/test_parking_api.py tests/test_foundation.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit the occupancy service**

```bash
git add backend/app/models/occupancy.py backend/app/services/occupancy.py backend/app/db.py tests/test_occupancy_service.py
git commit -m "feat: persist smoothed occupancy transitions"
```

---

### Task 5: Expose the Camera API and Complete the Milestone

**Files:**
- Create: `backend/app/routes/occupancy.py`
- Create: `tests/test_occupancy_api.py`
- Modify: `backend/app/main.py`
- Modify: `README.md`
- Modify: `progress.md`

**Interfaces:**
- Consumes: `OccupancyService.process(image_bytes: bytes)` from Task 4.
- Produces: `POST /api/camera/occupancy` with multipart field `image` and typed `OccupancyUpdateResponse`.
- Produces: structured `detail.code` input errors with HTTP 400 or 413.

- [ ] **Step 1: Write failing end-to-end API tests**

Post generated JPEG bytes and verify three requests move every configured slot
from pending to accepted, status reflects the committed result, and the number
and order of response slots match a non-five-slot configuration:

```python
response = client.post(
    "/api/camera/occupancy",
    files={"image": ("frame.jpg", frame_bytes, "image/jpeg")},
)
assert response.status_code == 200
assert [slot["slot_id"] for slot in response.json()["slots"]] == [2, 9, 21]
```

Add missing multipart field (422), empty JPEG (400 `empty_image`), PNG bytes
(400 `invalid_image`), oversized payload (413 `image_too_large`), and
out-of-bounds ROI (400 `roi_out_of_bounds`). Assert all failures leave database
rows and subsequent smoothing counts unchanged.

- [ ] **Step 2: Run API tests to verify route failure**

```bash
.venv/bin/python -m pytest tests/test_occupancy_api.py -q
```

Expected: FAIL with 404 because the route is not registered.

- [ ] **Step 3: Implement and wire the route**

Create the service once during application lifespan and expose:

```python
@router.post("/api/camera/occupancy", response_model=OccupancyUpdateResponse)
async def update_occupancy(
    request: Request,
    image: Annotated[UploadFile, File()],
) -> OccupancyUpdateResponse:
    payload = await image.read(request.app.state.settings.camera_max_image_bytes + 1)
    try:
        return request.app.state.occupancy_service.process(payload)
    except VisionInputError as exc:
        status = 413 if exc.code == "image_too_large" else 400
        raise HTTPException(
            status_code=status,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
```

Pass the configured maximum to the detector/service, include the router, and
ensure oversized input is rejected before image decode.

- [ ] **Step 4: Document configuration and API usage**

Update README language from fixed-five backend behavior to a five-slot default,
document ROI coordinates and calibration override, explain heuristic limits,
and add a working example:

```bash
curl -X POST http://127.0.0.1:8000/api/camera/occupancy \
  -F 'image=@frame.jpg;type=image/jpeg'
```

Update `progress.md` only after verification: mark the milestone complete, list
the exact test/lint evidence, record branch and implementation commit, and make
prediction comparison the next concrete task.

- [ ] **Step 5: Run focused and full verification**

```bash
.venv/bin/python -m pytest tests/test_occupancy_detector.py tests/test_occupancy_service.py tests/test_occupancy_api.py -q
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
git diff --check
```

Expected: all tests pass, Ruff reports no errors, and `git diff --check` emits
no output.

- [ ] **Step 6: Review and commit the completed milestone**

```bash
git status --short --branch
git diff
git add backend/app/main.py backend/app/routes/occupancy.py tests/test_occupancy_api.py README.md progress.md
git diff --cached --check
git diff --cached --stat
git diff --cached
git commit -m "feat: expose scalable camera occupancy API"
git show --stat --oneline HEAD
git status --short --branch
```

Expected: the commit contains only API, documentation, and milestone-state
changes; the working tree is clean and no push occurs unless explicitly
requested.
