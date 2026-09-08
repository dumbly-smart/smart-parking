# Prediction Training and Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate deterministic SQLite demo history and train, evaluate, publish, and compare real LSTM, GRU, and temporal Transformer models from one immutable `PreparedDataset`.

**Architecture:** A SQLite ownership ledger makes demo history transactionally replaceable without deleting real records. One training engine accepts only `PreparedDataset`, delegates model construction to TensorFlow builders, evaluates through shared NumPy metrics, and publishes content-addressed `.keras` artifacts through atomic JSON manifests.

**Tech Stack:** Python 3.11+, SQLite, NumPy 2.x, optional TensorFlow/Keras 2.20+, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-09-08-prediction-training-comparison-design.md`

## Global Constraints

- Preserve the fixed five-minute interval, twelve-step history, one-step horizon, feature order, scaling, and chronological split contract.
- Trainers accept `PreparedDataset`, never databases, source records, independently supplied arrays, or preprocessing configuration.
- TensorFlow is imported lazily; non-training imports work without the optional `ml` extra.
- All models share split roles, seeds, no-shuffle fitting, early stopping, loss, metrics, and latency measurement.
- Demo replacement deletes only ledger-owned rows for its explicit key in one `BEGIN IMMEDIATE` transaction.
- Generated RFID identifiers never appear in prepared data, errors, logs, manifests, or CLI output.
- Publish `.keras` bytes before atomically publishing a manifest; only manifests are discoverable.
- Do not persist `prediction_runs`, add APIs, select a runtime model, or add fallback inference.
- Ordinary tests run without TensorFlow; real-model smoke tests skip only when it is absent.

---

### Task 1: Shared training and evaluation contracts

**Files:**
- Create: `prediction/training.py`
- Create: `prediction/evaluation.py`
- Create: `tests/test_prediction_training.py`

**Interfaces:**
- Consumes: `PreparedDataset` and NumPy arrays.
- Produces: `PredictionTrainingError`, `ModelFamily`, `TrainingConfig`, `EvaluationMetrics`, `evaluate_predictions()`, `measure_inference_latency()`.

- [ ] **Step 1: Write failing tests**

```python
def test_evaluate_predictions_uses_literal_metrics():
    result = evaluate_predictions(np.array([0.0, 0.75]), np.array([0.25, 0.25]))
    assert result.mae == pytest.approx(0.375)
    assert result.mse == pytest.approx(0.15625)
    assert result.rmse == pytest.approx(math.sqrt(0.15625))
```

Also test invalid boolean/infinite/zero configuration, prediction rank/count/finite/range, latency warm-up exclusion, median elapsed time, and per-example normalization.

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/python -m pytest tests/test_prediction_training.py -v`

Expected: collection fails because the modules do not exist.

- [ ] **Step 3: Implement minimal contracts and metrics**

Define `ModelFamily(str, Enum)` in fixed LSTM/GRU/Transformer order. Define frozen validated `TrainingConfig` with seed 20260908, epochs 12, batch size 32, learning rate 0.001, patience 3, recurrent units 16, Transformer width 16, heads 2, and latency repetitions 5. Define frozen `EvaluationMetrics`. Accept prediction shapes `(n,)` and `(n, 1)`, copy to float64, and validate all values. Measure one unmeasured warm-up plus configured complete test calls using an injectable nanosecond clock.

- [ ] **Step 4: Verify GREEN and commit**

Run: `.venv/bin/python -m pytest tests/test_prediction_training.py -v`

Run: `.venv/bin/python -m ruff check prediction/training.py prediction/evaluation.py tests/test_prediction_training.py`

Commit: `feat: add shared prediction evaluation contracts`

### Task 2: Deterministic, safely replaceable demo history

**Files:**
- Modify: `backend/app/db.py`
- Create: `prediction/demo_data.py`
- Create: `scripts/seed_prediction_demo_data.py`
- Create: `tests/test_prediction_demo_data.py`
- Create: `tests/test_prediction_scripts.py`

**Interfaces:**
- Consumes: initialized `Database`, slot rows, immutable `DemoDataConfig`.
- Produces: `prediction_demo_records`, `replace_prediction_demo_data() -> DemoDataSummary`, CLI `main(argv) -> int`.

- [ ] **Step 1: Write failing behavior tests**

```python
def test_regeneration_reproduces_prepared_data(tmp_path):
    database = initialized_database(tmp_path)
    config = DemoDataConfig(dataset_key="demo", seed=11, start_at=START, days=7)
    replace_prediction_demo_data(database, config)
    first = prepare_prediction_dataset(database.load_prediction_source_data())
    replace_prediction_demo_data(database, config)
    second = prepare_prediction_dataset(database.load_prediction_source_data())
    np.testing.assert_array_equal(first.train.inputs, second.train.inputs)
    assert first.split_id == second.split_id
```

Also prove unrelated rows survive; different seeds change values; sessions are completed; occupancy stays within slot count; all feature families occur; an injected failure rolls back; invalid configs are typed; CLI output has counts but no RFID text/value.

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/python -m pytest tests/test_prediction_demo_data.py tests/test_prediction_scripts.py -v`

Expected: collection fails because demo interfaces do not exist.

- [ ] **Step 3: Add ownership schema and transaction boundary**

Add `prediction_demo_records(dataset_key, table_name, row_id)` with a composite primary key and CHECK restricting table names to context, vehicle, session, optimizer-run, and allocation tables. Add a narrow database transaction callback that executes `BEGIN IMMEDIATE` once.

- [ ] **Step 4: Implement generator and CLI**

Define defaults: key `prediction-demo`, seed 20260908, UTC start `2026-08-01T00:00:00Z`, 14 days. Validate key, non-boolean seed, aligned UTC start, and sufficient duration. Use only `random.Random(seed)`. Generate continuous five-minute contexts with bounded daily/weekly occupancy, weather, holiday/event pulses, plus completed sessions and matching allocations/objectives. Store synthetic RFID only in `vehicles`; never alter live slot occupancy. Delete prior owned IDs with fixed parameterized SQL in dependency order and record all new IDs in the same transaction. The argparse CLI initializes through existing settings and emits aggregate counts only.

- [ ] **Step 5: Verify GREEN and commit**

Run: `.venv/bin/python -m pytest tests/test_prediction_demo_data.py tests/test_prediction_scripts.py tests/test_prediction_data.py -v`

Run: `.venv/bin/python -m ruff check backend/app/db.py prediction/demo_data.py scripts/seed_prediction_demo_data.py tests/test_prediction_demo_data.py tests/test_prediction_scripts.py`

Commit: `feat: add deterministic prediction demo data`

### Task 3: TensorFlow builders and artifact manifests

**Files:**
- Create: `prediction/architectures.py`
- Create: `prediction/artifacts.py`
- Modify: `pyproject.toml`
- Modify: `tests/test_prediction_training.py`

**Interfaces:**
- Consumes: `TrainingConfig`, prepared input geometry, metrics, artifact directory.
- Produces: `configure_determinism()`, `build_model()`, `ArtifactManifest`, `publish_artifact()`, `load_manifest()`.

- [ ] **Step 1: Write failing builder and artifact tests**

Test lazy imports and typed missing dependency. When TensorFlow exists, each real builder must emit bounded `(n, 1)` output. With a real byte-writing fake saver, verify SHA-256, relative filenames, complete metadata, publication order, and reuse. Reject failed saves, malformed schema/JSON, traversal, tampering, non-finite metrics, feature/geometry mismatch, and expected `split_id` mismatch.

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/python -m pytest tests/test_prediction_training.py -v`

- [ ] **Step 3: Implement lazy real architectures**

Catch only `ImportError` and report `pip install -e '.[ml]'`. Seed Python, NumPy, and TensorFlow and enable deterministic operations. LSTM and GRU use equal recurrent width and scalar sigmoid heads. Transformer uses projection, deterministic positional encoding, multi-head attention, residual normalization, feed-forward residual, pooling, and scalar sigmoid head. Compile all with Adam/shared learning rate and MSE.

- [ ] **Step 4: Implement safe artifacts**

Save a unique staged `.keras`, hash it, move/reuse `<sha256>.keras`, then write canonical JSON to a sibling temp file, flush/fsync, and `os.replace` the stable manifest. Include schema/model/artifact hash, dataset identity/features/target/geometry, hyperparameters, split sizes, metrics/repetitions, framework versions, and UTC completion time. Validate safe basenames, containment, hash, all metadata, and expected dataset before loading model bytes.

- [ ] **Step 5: Verify GREEN and commit**

Run: `.venv/bin/python -m pytest tests/test_prediction_training.py -v`

Run: `.venv/bin/python -m ruff check prediction/architectures.py prediction/artifacts.py tests/test_prediction_training.py`

Commit: `feat: add prediction architectures and artifacts`

### Task 4: Shared comparison engine, command, and documentation

**Files:**
- Modify: `prediction/training.py`
- Create: `scripts/train_prediction_models.py`
- Modify: `tests/test_prediction_training.py`
- Modify: `tests/test_prediction_scripts.py`
- Modify: `README.md`
- Modify: `progress.md`

**Interfaces:**
- Consumes: exactly one `PreparedDataset`, one config per model family, artifact directory.
- Produces: `TrainingResult`, `train_model()`, `default_comparison_configs()`, `compare_models()`, CLI `main(argv) -> int`.

- [ ] **Step 1: Write failing orchestration tests**

```python
def test_comparison_passes_same_dataset_to_every_model(tmp_path):
    prepared = dataset()
    backend = RecordingBackend()
    results = compare_models(prepared, default_comparison_configs(), tmp_path, _backend=backend)
    assert backend.datasets == [prepared, prepared, prepared]
    assert [result.model for result in results] == list(ModelFamily)
```

Also prove train/validation/test role isolation, no shuffle, shared early stopping, fixed result order, duplicate/missing config rejection, exact dataset contract checks, artifact linkage, CLI calling existing load/preparation once, and actionable missing-ML output.

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/python -m pytest tests/test_prediction_training.py tests/test_prediction_scripts.py -v`

- [ ] **Step 3: Implement engine and CLI**

The internal backend receives the same dataset object but fits only train, validates only validation, predicts metrics from test, and repeats immutable test inference only for latency. TensorFlow fitting uses `shuffle=False` and `EarlyStopping(monitor="val_loss", restore_best_weights=True, patience=config.patience)`. Require exactly all three families and fixed output order. CLI initializes the selected database, loads source once, prepares once, compares once, and emits only model/metrics/split/manifest data.

- [ ] **Step 4: Run full verification**

Run: `.venv/bin/python -m pytest tests/test_prediction_data.py tests/test_prediction_demo_data.py tests/test_prediction_training.py tests/test_prediction_scripts.py -v`

Run: `.venv/bin/python -m pytest -q`

Run: `.venv/bin/python -m ruff check .`

Run: `git diff --check`

- [ ] **Step 5: Document and commit**

Document seeding, `.[ml]` install, all-model training, shared dataset guarantee, manifests, and GRU as the recommended affordable runtime candidate pending measured results. Correct the stale preprocessing counts to 72/162 and update `progress.md` with fresh final counts while keeping Prediction comparison in progress.

Commit: `feat: train and compare prediction models`
