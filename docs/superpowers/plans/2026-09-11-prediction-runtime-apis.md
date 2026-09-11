# Prediction Persistence and Runtime APIs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist validated prediction-comparison manifests and safely serve cached, five-minute runtime forecasts.

**Architecture:** SQLite stores typed, whitelisted summaries only after manifest validation. Shared prediction data constructs the runtime window; a service validates a schema-v2 artifact contract before lazy model loading and otherwise returns a deterministic baseline.

**Tech Stack:** Python 3.11+, FastAPI, SQLite, NumPy, optional TensorFlow/Keras, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-09-11-prediction-runtime-apis-design.md`

## Global Constraints

- Preserve `PreparedDataset` as the sole training/preprocessing split boundary.
- Runtime uses the existing fixed five-minute interval, twelve-step history, and one-step horizon.
- RFID identifiers must not appear in inputs, logs, manifests, stored summaries, or API responses.
- Validate split ID, feature order, geometry, scaler, manifest, artifact basename, and SHA-256 before model loading.
- Manifest schema v2 stores only fitted scaler metadata; v1 is history-only and never runtime-compatible.
- Runtime never trains, and unsafe/missing artifacts deterministically fall back.

---

### Task 1: Runtime-compatible shared contracts

**Files:**
- Modify: `prediction/data.py`, `prediction/artifacts.py`, `tests/test_prediction_data.py`, `tests/test_prediction_training.py`

**Interfaces:**
- Produces: `RuntimeInput`, `build_runtime_input(source, dataset)`, schema-v2 `ArtifactManifest` validation.

- [ ] **Step 1: Write failing tests**

```python
def test_runtime_input_uses_latest_aligned_twelve_bucket_window() -> None:
    dataset = prepare_prediction_dataset(regular_prediction_source(bucket_count=120))
    runtime = build_runtime_input(regular_prediction_source(bucket_count=120), dataset)
    assert runtime.target_at.minute % 5 == 0
    assert runtime.inputs.shape == (1, 12, len(FEATURE_NAMES))
```

Add literal tests that a changed privacy-safe timeline changes `split_id`,
that the fitted scaler is required and compared, and that v1 manifests cannot
be runtime compatible.

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/python -m pytest tests/test_prediction_data.py tests/test_prediction_training.py -q`

Expected: failure because `build_runtime_input` and scaler manifest fields do
not exist.

- [ ] **Step 3: Implement shared runtime data and schema-v2 validation**

Build the latest complete window solely from `build_feature_timeline`, require
the fixed geometry, copy and scale continuous values with `dataset.scaler`,
and return a read-only `(1, 12, feature_count)` array plus next aligned UTC
timestamp and latest occupancy ratio. Hash canonical timeline values into
`split_id`. Store and validate scaler metadata in v2 manifests, retaining v1
parsing for persisted history only.

- [ ] **Step 4: Verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_prediction_data.py tests/test_prediction_training.py -q`

### Task 2: Atomic prediction-result persistence

**Files:**
- Modify: `backend/app/db.py`, `prediction/models.py`, `scripts/train_prediction_models.py`, `tests/test_prediction_training.py`, `tests/test_prediction_scripts.py`

**Interfaces:**
- Produces: `PersistedPredictionRun`, `Database.save_prediction_results(results)`, `Database.list_prediction_results()`.

- [ ] **Step 1: Write failing tests**

```python
def test_prediction_result_persistence_rolls_back_all_rows(tmp_path: Path) -> None:
    database = initialized_database(tmp_path)
    with pytest.raises(sqlite3.IntegrityError):
        database.save_prediction_results(results_with_second_insert_rejected())
    assert database.list_prediction_results() == []
```

Also prove a tampered manifest is rejected before insertion and serialized
metadata has no RFID text or artifact directory path.

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/python -m pytest tests/test_prediction_training.py tests/test_prediction_scripts.py -q`

Expected: failure because the prediction-result database methods do not exist.

- [ ] **Step 3: Implement atomic validation and storage**

Resolve each result’s manifest using `load_manifest`, require its model and
split ID to match the result, serialize a fixed safe manifest summary, and
insert the complete batch under one transaction. Make the CLI save only after
the whole comparison succeeds.

- [ ] **Step 4: Verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_prediction_training.py tests/test_prediction_scripts.py -q`

### Task 3: Predictor comparison and runtime service/API

**Files:**
- Create: `backend/app/services/prediction.py`, `backend/app/routes/prediction.py`
- Modify: `backend/app/config.py`, `backend/app/main.py`, `.env.example`, `tests/test_prediction_training.py`, `tests/test_prediction_scripts.py`

**Interfaces:**
- Produces: `PredictionService.forecast()`, `GET /api/prediction`, `GET /api/benchmarks/predictors`.

- [ ] **Step 1: Write failing service and API tests**

```python
def test_prediction_api_falls_back_without_compatible_artifact(client: TestClient) -> None:
    response = client.get('/api/prediction')
    assert response.status_code == 200
    assert response.json()['model'] == 'baseline'
    assert response.json()['fallback_reason'] == 'no_compatible_artifact'
```

Add tests for split/feature/geometry/hash rejection before fake loader use,
invalid outputs, one-load-per-bucket caching, selected-model success, typed
benchmark listing, and absence of any RFID key/value in both response bodies.

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/python -m pytest tests/test_prediction_training.py tests/test_prediction_scripts.py -q`

Expected: routes and service imports fail because they do not exist.

- [ ] **Step 3: Implement service and routes**

Add an artifact-directory setting. Prepare source once per forecast, use the
shared runtime input, select the newest persisted compatible manifest for the
configured model, lazy-load only after validation, verify a one-value bounded
prediction, and cache immutable responses by target bucket. Return baseline
and stable reason for all safe-degradation paths.

- [ ] **Step 4: Verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_prediction_training.py tests/test_prediction_scripts.py -q`

### Task 4: Documentation and full verification

**Files:**
- Modify: `README.md`, `architecture.md`, `decisions.md`, `progress.md`, `index.md`

- [ ] **Step 1: Document runtime selection and fallback**

Document the artifact directory setting, predictor comparison endpoint,
five-minute forecast response, validation/fallback behavior, and schema-v2
scaler contract. Add an ADR for the public artifact-compatibility change.

- [ ] **Step 2: Run focused tests**

Run: `.venv/bin/python -m pytest tests/test_prediction_data.py tests/test_prediction_training.py tests/test_prediction_scripts.py -q`

- [ ] **Step 3: Run complete verification**

Run: `.venv/bin/python -m pytest -q`

Run: `.venv/bin/python -m ruff check .`

Run: `git diff --check`

- [ ] **Step 4: Update progress and commit**

Record fresh focused/full counts, skipped optional TensorFlow tests, warnings,
branch, and next task in `progress.md`. Commit all feature files as
`feat: add prediction persistence and runtime APIs` after reviewing the staged
diff. Do not push.
