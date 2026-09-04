# Shared Prediction Preprocessing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one deterministic SQLite-backed preprocessing pipeline that gives future LSTM, GRU, and Transformer trainers identical leakage-safe five-minute time-series datasets.

**Architecture:** Add immutable prediction contracts, a read-only database extraction boundary, five-minute feature aggregation, and chronological sequence preparation. NumPy is the only numerical dependency; raw RFID values remain inside the lifecycle database and never enter prepared model data.

**Tech Stack:** Python 3.11+, standard-library SQLite/dataclasses/datetime/hashlib/json/math, NumPy 2.x, Pydantic 2.x, pytest, Ruff

**Spec:** `docs/superpowers/specs/2026-09-04-shared-prediction-preprocessing-design.md`

## Global Constraints

- The forecast interval is exactly five minutes.
- Each example uses twelve prior buckets to predict the immediately following bucket.
- The target is total occupancy normalized by the configured slot count and remains in `[0, 1]`.
- Split the regular bucket timeline chronologically using 70 percent train, 15 percent validation, and the remainder test.
- Split buckets before constructing examples; no sequence may cross a partition boundary.
- Fit continuous-feature means and population standard deviations on training inputs only; replace a zero standard deviation with one.
- Do not rescale the occupancy target or naturally bounded boolean, one-hot, and cyclic features.
- Carry occupancy and weather forward across at most three missing buckets by default.
- Raw RFID values and stable vehicle identifiers must not appear in prepared arrays, metadata, hashes, logs, or validation errors.
- Objective features come from the objective breakdown stored with the allocation, not from current optimizer configuration.
- Do not add TensorFlow, Pandas, scikit-learn, model training, synthetic-data commands, prediction APIs, or dashboard behavior.

---

### Task 1: Immutable Prediction Data Contracts

**Files:**
- Create: `prediction/__init__.py`
- Create: `prediction/models.py`
- Create: `tests/test_prediction_data.py`

**Interfaces:**
- Consumes: NumPy arrays and standard Python source-record values.
- Produces: `PredictionDataError`, `PreprocessingConfig`, `ContextSampleRecord`, `SessionRecord`, `AllocationFeatureRecord`, `PredictionSourceData`, `FeatureBucket`, `ScalerMetadata`, `PreparedSplit`, `PreparedDataset`, `WEATHER_CATEGORIES`, `FEATURE_NAMES`, and `CONTINUOUS_FEATURE_NAMES`.

- [ ] **Step 1: Write failing contract tests**

Create `tests/test_prediction_data.py` with imports and tests that establish validated defaults and deep array immutability:

```python
from datetime import UTC, datetime

import numpy as np
import pytest

from prediction.models import (
    FEATURE_NAMES,
    PreparedSplit,
    PreprocessingConfig,
    PredictionDataError,
)


def test_preprocessing_config_has_approved_defaults() -> None:
    config = PreprocessingConfig()

    assert config.interval_minutes == 5
    assert config.lookback_steps == 12
    assert config.horizon_steps == 1
    assert config.train_fraction == 0.70
    assert config.validation_fraction == 0.15
    assert config.max_carry_intervals == 3


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"interval_minutes": 0}, "invalid_config"),
        ({"lookback_steps": 0}, "invalid_config"),
        ({"horizon_steps": 0}, "invalid_config"),
        ({"train_fraction": 0.9, "validation_fraction": 0.2}, "invalid_config"),
        ({"max_carry_intervals": -1}, "invalid_config"),
    ],
)
def test_preprocessing_config_rejects_invalid_values(
    overrides: dict[str, object], code: str
) -> None:
    with pytest.raises(PredictionDataError) as raised:
        PreprocessingConfig(**overrides)

    assert raised.value.code == code


def test_prepared_split_copies_and_freezes_arrays() -> None:
    source_inputs = np.zeros((2, 12, len(FEATURE_NAMES)), dtype=np.float64)
    source_targets = np.array([0.2, 0.4], dtype=np.float64)
    split = PreparedSplit(
        inputs=source_inputs,
        targets=source_targets,
        target_timestamps=(
            datetime(2026, 9, 4, 10, tzinfo=UTC),
            datetime(2026, 9, 4, 10, 5, tzinfo=UTC),
        ),
    )
    source_inputs[0, 0, 0] = 99

    assert split.inputs[0, 0, 0] == 0
    assert not split.inputs.flags.writeable
    assert not split.targets.flags.writeable
    with pytest.raises(ValueError):
        split.inputs[0, 0, 0] = 1
```

- [ ] **Step 2: Run the contract tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_prediction_data.py -v
```

Expected: collection fails with `ModuleNotFoundError: No module named 'prediction'`.

- [ ] **Step 3: Implement the contracts and fixed feature vocabulary**

Create an empty `prediction/__init__.py`. In `prediction/models.py`, define the fixed order explicitly:

```python
WEATHER_CATEGORIES = ("clear", "cloudy", "rain", "fog", "storm", "snow", "other")

FEATURE_NAMES = (
    "occupancy_ratio",
    "occupancy_change",
    "occupancy_mean_15m",
    "occupancy_mean_60m",
    "hour_sin",
    "hour_cos",
    "weekday_sin",
    "weekday_cos",
    *(f"weather_{category}" for category in WEATHER_CATEGORIES),
    "holiday",
    "event",
    "entry_count",
    "exit_count",
    "allocation_count",
    "active_session_count",
    "unique_vehicle_count",
    "returning_vehicle_rate",
    "mean_walking_distance",
    "mean_congestion",
    "mean_fairness",
    "allocation_present",
)

CONTINUOUS_FEATURE_NAMES = (
    "occupancy_ratio",
    "occupancy_change",
    "occupancy_mean_15m",
    "occupancy_mean_60m",
    "entry_count",
    "exit_count",
    "allocation_count",
    "active_session_count",
    "unique_vehicle_count",
    "returning_vehicle_rate",
    "mean_walking_distance",
    "mean_congestion",
    "mean_fairness",
)
```

Define `PredictionDataError(ValueError)` with stable `code` and `message`
attributes. Implement a frozen `PreprocessingConfig` dataclass whose
`__post_init__` raises `PredictionDataError("invalid_config", message)` unless
interval, lookback, and horizon are positive; both fractions are strictly
between zero and one and sum to less than one; and the carry limit is
non-negative. Use messages that name the invalid field and accepted range.

Use frozen dataclasses with these exact fields:

```python
@dataclass(frozen=True)
class ContextSampleRecord:
    id: int
    occupancy_count: int
    weather: str
    holiday: int
    event: int
    sampled_at: str


@dataclass(frozen=True)
class SessionRecord:
    id: int
    vehicle_id: int
    entered_at: str
    exited_at: str | None


@dataclass(frozen=True)
class AllocationFeatureRecord:
    id: int
    vehicle_id: int
    created_at: str
    objective_breakdown_json: str


@dataclass(frozen=True)
class PredictionSourceData:
    slot_count: int
    context_samples: tuple[ContextSampleRecord, ...]
    sessions: tuple[SessionRecord, ...]
    allocations: tuple[AllocationFeatureRecord, ...]


@dataclass(frozen=True)
class FeatureBucket:
    timestamp: datetime
    values: tuple[float, ...]


@dataclass(frozen=True)
class ScalerMetadata:
    feature_indices: tuple[int, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]


@dataclass(frozen=True)
class PreparedSplit:
    inputs: np.ndarray
    targets: np.ndarray
    target_timestamps: tuple[datetime, ...]


@dataclass(frozen=True)
class PreparedDataset:
    feature_names: tuple[str, ...]
    target_name: str
    train: PreparedSplit
    validation: PreparedSplit
    test: PreparedSplit
    scaler: ScalerMetadata
    split_id: str
    source_started_at: datetime
    source_ended_at: datetime
    train_ended_at: datetime
    validation_ended_at: datetime
    config: PreprocessingConfig
    slot_count: int
```

In `PreparedSplit.__post_init__`, coerce copies to `np.float64`, require shapes `(examples, lookback, features)` and `(examples,)`, require timestamp count to match, require all values to be finite, then call `setflags(write=False)` and assign through `object.__setattr__`. Validate `PreparedDataset` feature names, non-empty splits, chronological boundaries, target range, and positive slot count with stable codes `invalid_dataset` or `empty_split`.

- [ ] **Step 4: Run the contract tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_prediction_data.py -v
.venv/bin/python -m ruff check prediction tests/test_prediction_data.py
```

Expected: all contract tests pass and Ruff reports no errors.

- [ ] **Step 5: Commit the contract slice**

```bash
git add prediction/__init__.py prediction/models.py tests/test_prediction_data.py
git commit -m "feat: define prediction preprocessing contracts"
```

---

### Task 2: Read-Only SQLite Prediction Source Boundary

**Files:**
- Modify: `backend/app/db.py:1-20,628-701`
- Modify: `tests/test_prediction_data.py`

**Interfaces:**
- Consumes: Existing `context_samples`, `parking_sessions`, `allocations`, and `optimizer_runs` tables.
- Produces: `Database.load_prediction_source_data() -> PredictionSourceData` ordered by timestamp and database ID without selecting `vehicles.rfid_uid`.

- [ ] **Step 1: Add a failing extraction and privacy test**

Add a fixture that initializes two configured slots, inserts context rows out of insertion order, inserts one vehicle/session/allocation/optimizer result, and then asserts the typed source boundary:

```python
def test_database_loads_ordered_prediction_sources_without_rfid(tmp_path: Path) -> None:
    database = initialized_prediction_database(tmp_path, slot_ids=(2, 9))
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO context_samples "
            "(occupancy_count, weather, holiday, event, sampled_at) "
            "VALUES (1, 'rain', 0, 1, '2026-09-04T10:05:00Z')"
        )
        connection.execute(
            "INSERT INTO context_samples "
            "(occupancy_count, weather, holiday, event, sampled_at) "
            "VALUES (0, 'clear', 0, 0, '2026-09-04T10:00:00Z')"
        )
        insert_lifecycle_allocation(
            connection,
            rfid_uid="private-tag",
            entered_at="2026-09-04T10:02:00Z",
            distance=0.25,
            congestion=0.5,
            fairness=0.75,
        )

    source = database.load_prediction_source_data()

    assert source.slot_count == 2
    assert [row.sampled_at for row in source.context_samples] == [
        "2026-09-04T10:00:00Z",
        "2026-09-04T10:05:00Z",
    ]
    assert source.sessions[0].vehicle_id == source.allocations[0].vehicle_id
    assert "private-tag" not in repr(source)
```

The test helper must insert `objective_breakdown` with `json.dumps` and return generated IDs; use explicit timestamps rather than SQLite clock defaults.

- [ ] **Step 2: Run the extraction test and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_prediction_data.py::test_database_loads_ordered_prediction_sources_without_rfid -v
```

Expected: FAIL with `AttributeError: 'Database' object has no attribute 'load_prediction_source_data'`.

- [ ] **Step 3: Implement one consistent read snapshot**

Import the four source dataclasses from `prediction.models`. Add `Database.load_prediction_source_data` using one connection and one deferred read transaction:

```python
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
```

Do not join the `vehicles` table and do not select `rfid_uid`. The transaction ensures all three record collections describe one database snapshot.

- [ ] **Step 4: Verify ordering, snapshot shape, and existing database behavior**

Run:

```bash
.venv/bin/python -m pytest tests/test_prediction_data.py::test_database_loads_ordered_prediction_sources_without_rfid tests/test_foundation.py tests/test_parking_api.py -v
.venv/bin/python -m ruff check backend/app/db.py tests/test_prediction_data.py
```

Expected: all selected tests pass and Ruff reports no errors.

- [ ] **Step 5: Commit the extraction boundary**

```bash
git add backend/app/db.py tests/test_prediction_data.py
git commit -m "feat: expose prediction source snapshot"
```

---

### Task 3: Five-Minute Aggregation and Feature Engineering

**Files:**
- Create: `prediction/data.py`
- Modify: `tests/test_prediction_data.py`

**Interfaces:**
- Consumes: `PredictionSourceData` and `PreprocessingConfig`.
- Produces: `build_feature_timeline(source: PredictionSourceData, config: PreprocessingConfig) -> tuple[FeatureBucket | None, ...]` and `parse_utc_timestamp(value: str, field: str) -> datetime`.

- [ ] **Step 1: Write failing feature aggregation tests**

Add a source-data builder that produces at least thirteen regular buckets and tests the exact first complete bucket values by looking them up through `FEATURE_NAMES`:

```python
def feature(bucket: FeatureBucket, name: str) -> float:
    return bucket.values[FEATURE_NAMES.index(name)]


def test_feature_timeline_aggregates_context_sessions_and_allocations() -> None:
    source = prediction_source(
        slot_count=4,
        context_counts=[0, 1, 2, 2, 3, 3, 2, 2, 1, 1, 2, 3, 4],
        weather="rain",
        holiday=1,
        event=1,
        sessions=(
            session(1, vehicle_id=7, entered_at="2026-09-04T10:01:00Z"),
            session(2, vehicle_id=7, entered_at="2026-09-04T10:06:00Z"),
        ),
        allocations=(
            allocation(
                1,
                vehicle_id=7,
                created_at="2026-09-04T10:02:00Z",
                distance=0.25,
                congestion=0.5,
                fairness=0.75,
            ),
        ),
    )

    timeline = build_feature_timeline(source, PreprocessingConfig())
    first = timeline[0]

    assert first is not None
    assert feature(first, "occupancy_ratio") == 0
    assert feature(first, "entry_count") == 1
    assert feature(first, "unique_vehicle_count") == 1
    assert feature(first, "allocation_count") == 1
    assert feature(first, "mean_walking_distance") == 0.25
    assert feature(first, "mean_congestion") == 0.5
    assert feature(first, "mean_fairness") == 0.75
    assert feature(first, "weather_rain") == 1
    assert feature(first, "holiday") == 1
    assert feature(first, "event") == 1
    assert all(np.isfinite(first.values))


def test_feature_timeline_carries_short_gaps_and_preserves_long_gaps() -> None:
    source = source_with_context_minutes((0, 20, 25, 30), slot_count=5)

    timeline = build_feature_timeline(source, PreprocessingConfig())

    assert [bucket is None for bucket in timeline[:7]] == [
        False,
        False,
        False,
        False,
        False,
        False,
        False,
    ]
    source = source_with_context_minutes((0, 25, 30), slot_count=5)
    timeline = build_feature_timeline(source, PreprocessingConfig())
    assert timeline[4] is None
```

Also add parameterized failures for slot count zero, occupancy above slot count, naive/malformed timestamps, invalid flags, invalid/non-finite objective JSON, and exit timestamps before entry. Assert stable codes such as `invalid_slot_count`, `invalid_occupancy`, `invalid_timestamp`, `invalid_flag`, `invalid_objective`, and `invalid_session`.

- [ ] **Step 2: Run aggregation tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_prediction_data.py -k "timeline or invalid_" -v
```

Expected: collection fails because `prediction.data` does not exist.

- [ ] **Step 3: Implement timestamp parsing, validation, and bucketing**

In `prediction/data.py`, normalize a trailing `Z` to `+00:00`, call `datetime.fromisoformat`, reject naive timestamps, and return UTC. Floor timestamps to `config.interval_minutes` using integer epoch seconds. Build the inclusive grid from the earliest to latest context bucket.

Parse and sort context records by `(sampled_at, id)`, sessions by
`(entered_at, id)`, and allocations by `(created_at, id)` inside this function;
do not rely on callers to preserve database ordering. Reject duplicate IDs
within each record collection. This gives direct in-memory callers the same
determinism as the SQLite adapter.

For multiple context rows in one bucket, use the row with greatest `(parsed_timestamp, id)`. Carry its occupancy and weather through at most `max_carry_intervals` absent buckets. Holiday and event use the selected/carried context record consistently. Emit `None` after the carry limit until another context record resolves the timeline.

Validate objective JSON with this concrete shape before aggregation:

```python
payload = json.loads(record.objective_breakdown_json)
values = tuple(float(payload[key]) for key in ("distance", "congestion", "fairness"))
if not all(math.isfinite(value) and 0 <= value <= 1 for value in values):
    raise PredictionDataError("invalid_objective", "objective values must be finite in [0, 1]")
```

Assign entries, exits, and allocations to half-open bucket intervals `[start, end)`. Define active sessions at bucket end as `entered_at < end` and `exited_at is None or exited_at >= end`. `unique_vehicle_count` counts the union of vehicle IDs with an entry or exit in the bucket. `returning_vehicle_rate` is returning entries divided by entries, where a vehicle is returning if it has any earlier session entry before the current bucket.

- [ ] **Step 4: Implement exact feature calculations**

For each resolved bucket, create the tuple in `FEATURE_NAMES` order. Use:

```python
occupancy_ratio = occupancy_count / source.slot_count
occupancy_change = occupancy_ratio - previous_resolved_ratio
mean_15m = float(np.mean(resolved_ratios_since_gap[-3:]))
mean_60m = float(np.mean(resolved_ratios_since_gap[-12:]))
hour = timestamp.hour + timestamp.minute / 60
hour_angle = 2 * math.pi * hour / 24
weekday_angle = 2 * math.pi * timestamp.weekday() / 7
```

The first ratio after the start or an unresolved gap has change zero. Rolling means use up to the available three or twelve current-and-prior resolved ratios and reset after a gap. Normalize weather with `strip().lower()` and use `other` when it is outside `WEATHER_CATEGORIES[:-1]`. Build one-hot weather values in vocabulary order. Empty allocation buckets use zero means and `allocation_present=0`; non-empty buckets average their stored unweighted distance, congestion, and fairness values and set the flag to one.

Before returning, require `len(values) == len(FEATURE_NAMES)` and every value to be finite. Never place raw RFID strings or vehicle IDs in `FeatureBucket`.

- [ ] **Step 5: Run aggregation tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_prediction_data.py -k "timeline or feature or invalid_" -v
.venv/bin/python -m ruff check prediction tests/test_prediction_data.py
```

Expected: all selected tests pass and Ruff reports no errors.

- [ ] **Step 6: Commit feature engineering**

```bash
git add prediction/data.py tests/test_prediction_data.py
git commit -m "feat: aggregate prediction features"
```

---

### Task 4: Leakage-Safe Sequencing, Scaling, and Split Identity

**Files:**
- Modify: `prediction/data.py`
- Modify: `tests/test_prediction_data.py`

**Interfaces:**
- Consumes: `build_feature_timeline`, `FEATURE_NAMES`, `CONTINUOUS_FEATURE_NAMES`, and the immutable contracts from Task 1.
- Produces: `prepare_prediction_dataset(source: PredictionSourceData, config: PreprocessingConfig | None = None) -> PreparedDataset`.

- [ ] **Step 1: Write failing split, scaling, and determinism tests**

Create at least 120 regular source buckets so every partition can independently produce twelve-step examples. Assert exact floor boundaries, shapes, target timestamps, and no cross-boundary history:

```python
def test_prepared_dataset_uses_independent_chronological_splits() -> None:
    source = regular_prediction_source(bucket_count=120, slot_count=8)

    dataset = prepare_prediction_dataset(source)

    assert dataset.train.inputs.shape == (72, 12, len(FEATURE_NAMES))
    assert dataset.validation.inputs.shape == (6, 12, len(FEATURE_NAMES))
    assert dataset.test.inputs.shape == (6, 12, len(FEATURE_NAMES))
    assert dataset.train.target_timestamps[-1] <= dataset.train_ended_at
    assert dataset.validation.target_timestamps[0] > dataset.train_ended_at
    assert dataset.test.target_timestamps[0] > dataset.validation_ended_at
```

The expected counts follow bucket partitions of 84, 18, and 18; each loses twelve lookback buckets when the one-step target is built.

Add a leakage test where validation/test continuous values are extreme and assert `dataset.scaler.means` and `scales` equal statistics computed from unscaled training inputs only. Add a zero-variance feature assertion for scale one. Assert booleans, cyclic values, weather one-hot values, and targets remain unscaled.

Add a gap test proving no example contains timestamps spanning a `None` bucket. Add an insufficient-data test expecting `PredictionDataError.code == "empty_split"`. Run preparation twice and use `np.testing.assert_array_equal` plus equal `split_id` assertions.

- [ ] **Step 2: Run preparation tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_prediction_data.py -k "prepared or scaling or deterministic or empty_split" -v
```

Expected: FAIL because `prepare_prediction_dataset` is not defined.

- [ ] **Step 3: Split buckets first and build independent examples**

Implement helpers with these exact signatures:

```python
def _split_timeline(
    timeline: tuple[FeatureBucket | None, ...], config: PreprocessingConfig
) -> tuple[
    tuple[FeatureBucket | None, ...],
    tuple[FeatureBucket | None, ...],
    tuple[FeatureBucket | None, ...],
]:
    train_end = math.floor(len(timeline) * config.train_fraction)
    validation_end = train_end + math.floor(
        len(timeline) * config.validation_fraction
    )
    return (
        timeline[:train_end],
        timeline[train_end:validation_end],
        timeline[validation_end:],
    )


def _build_examples(
    buckets: tuple[FeatureBucket | None, ...], config: PreprocessingConfig
) -> tuple[np.ndarray, np.ndarray, tuple[datetime, ...]]:
    inputs: list[tuple[tuple[float, ...], ...]] = []
    targets: list[float] = []
    timestamps: list[datetime] = []
    target_offset = config.lookback_steps + config.horizon_steps - 1
    target_feature = FEATURE_NAMES.index("occupancy_ratio")
    for target_index in range(target_offset, len(buckets)):
        input_end = target_index - config.horizon_steps + 1
        input_start = input_end - config.lookback_steps
        window = buckets[input_start:input_end]
        target_bucket = buckets[target_index]
        if target_bucket is None or any(bucket is None for bucket in window):
            continue
        resolved_window = cast(tuple[FeatureBucket, ...], window)
        inputs.append(tuple(bucket.values for bucket in resolved_window))
        targets.append(target_bucket.values[target_feature])
        timestamps.append(target_bucket.timestamp)
    return (
        np.asarray(inputs, dtype=np.float64).reshape(
            -1, config.lookback_steps, len(FEATURE_NAMES)
        ),
        np.asarray(targets, dtype=np.float64),
        tuple(timestamps),
    )
```

Compute `train_end = floor(N * train_fraction)` and `validation_end = train_end + floor(N * validation_fraction)`. `_build_examples` iterates target indices from `lookback_steps + horizon_steps - 1` onward. Its input ends `horizon_steps` before or at the target as appropriate; for the approved one-step horizon, input indices are `[target-lookback_steps:target]`. Skip an example if any input or target bucket is `None`. Read the target from the target bucket's `occupancy_ratio` feature. Raise `empty_split` naming the partition in `prepare_prediction_dataset` when any resulting split has no examples.

- [ ] **Step 4: Fit and apply training-only scaling**

Resolve continuous indices and fit exact training-only statistics:

```python
continuous_indices = tuple(
    FEATURE_NAMES.index(name) for name in CONTINUOUS_FEATURE_NAMES
)
training_continuous = train_inputs[:, :, continuous_indices].reshape(
    -1, len(continuous_indices)
)
means = np.mean(training_continuous, axis=0)
scales = np.std(training_continuous, axis=0, ddof=0)
scales = np.where(scales == 0, 1.0, scales)
for inputs in (train_inputs, validation_inputs, test_inputs):
    inputs[:, :, continuous_indices] = (
        inputs[:, :, continuous_indices] - means
    ) / scales
```

Do not transform targets or non-continuous feature columns.

Construct each `PreparedSplit` only after scaling so its defensive copy becomes read-only. Store scaler values as tuples in continuous-index order.

- [ ] **Step 5: Generate a stable split identifier and dataset**

Build canonical JSON with sorted keys and compact separators from:

```python
identity = {
    "config": asdict(config),
    "feature_names": FEATURE_NAMES,
    "target_name": "next_occupancy_ratio",
    "slot_count": source.slot_count,
    "source_started_at": timeline[0].timestamp.isoformat(),
    "source_ended_at": timeline[-1].timestamp.isoformat(),
    "train_ended_at": train_timeline[-1].timestamp.isoformat(),
    "validation_ended_at": validation_timeline[-1].timestamp.isoformat(),
}
split_id = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
```

Require boundary buckets to be resolved; otherwise use the closest preceding resolved timestamp within that partition and raise `empty_split` if none exists. Return `PreparedDataset` with the three splits, scaler, metadata, configuration, and slot count.

- [ ] **Step 6: Run prediction tests and full regression tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_prediction_data.py -v
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
git diff --check
```

Expected: prediction tests and all existing tests pass, Ruff reports no errors, and `git diff --check` emits no output. Only the two documented FastAPI/Starlette dependency warnings may remain.

- [ ] **Step 7: Commit prepared dataset behavior**

```bash
git add prediction/data.py tests/test_prediction_data.py
git commit -m "feat: prepare shared prediction splits"
```

---

### Task 5: Document the Shared Preprocessing Slice

**Files:**
- Modify: `README.md:136-139`
- Modify: `progress.md:5-26,28-45`

**Interfaces:**
- Consumes: Verified behavior and exact command results from Tasks 1-4.
- Produces: User-facing preprocessing documentation and an accurate milestone handoff.

- [ ] **Step 1: Add README documentation**

After the camera section, add `## Prediction preprocessing` explaining:

```markdown
Prediction preprocessing reads persisted context, lifecycle, allocation, and
optimizer records into regular five-minute buckets. Every future predictor
uses the same chronological 70/15/15 split: twelve historical buckets (one
hour) predict the next bucket's normalized occupancy.

Features include occupancy trends, cyclic time, weather, holiday/event state,
entry/exit activity, active sessions, returning-vehicle rate, and aggregate
walking-distance, congestion, and fairness values. RFID identifiers remain in
the lifecycle boundary and are never included in model arrays. Continuous
features are standardized from training data only, preventing validation/test
leakage. Runtime inference will be cached per five-minute bucket in a later
prediction-service slice; model training will never occur inside an API
request.
```

- [ ] **Step 2: Update progress only after verification**

Keep `Prediction comparison` marked in progress rather than complete. Add a
completed-session entry listing the preprocessing contracts, five-minute
aggregation, privacy-preserving RFID aggregates, leakage-safe split/scaling,
and the exact focused/full test counts observed in Task 4. Set the next task to
the deterministic demo-data generator and shared model-training/evaluation
boundary.

- [ ] **Step 3: Run final documentation and repository verification**

Run:

```bash
.venv/bin/python -m pytest tests/test_prediction_data.py -q
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
git diff --check
git status --short
```

Expected: focused and full suites pass, Ruff reports no errors,
`git diff --check` emits no output, and status lists only the intended README
and progress changes.

- [ ] **Step 4: Commit documentation and verified project state**

```bash
git add README.md progress.md
git commit -m "docs: record shared prediction preprocessing"
```

- [ ] **Step 5: Inspect the final milestone slice**

Run:

```bash
git log --oneline -5
git status --short
```

Expected: the five planned commits are visible and the worktree is clean.
