# Prediction Training and Comparison Design

## Scope

This slice adds deterministic demo history plus real TensorFlow/Keras LSTM,
GRU, and temporal Transformer training behind one shared training and
evaluation boundary. Every trainer consumes the existing immutable
`PreparedDataset`; no trainer may query SQLite or perform private aggregation,
feature engineering, scaling, or splitting.

The slice produces native Keras model artifacts and small JSON manifests on
the filesystem. It does not persist `prediction_runs`, expose comparison or
runtime prediction APIs, select a production model, or implement the runtime
fallback. Those remain follow-on work.

TensorFlow remains an optional dependency. Demo generation, preprocessing, and
normal application startup continue to work without the `ml` extra installed.

## End-to-End Workflow

1. An operator invokes the demo generator with an explicit SQLite database,
   integer seed, timezone-aware UTC start, duration, five-minute interval, and
   dataset key.
2. The generator transactionally replaces only records previously attributed
   to that dataset key, then inserts deterministic context samples, completed
   sessions, optimizer runs, and allocations.
3. The existing `Database.load_prediction_source_data()` returns one ordered,
   privacy-preserving source snapshot.
4. The existing `prepare_prediction_dataset()` produces the sole immutable
   `PreparedDataset`, including its chronological train/validation/test splits,
   training-only scaler, and stable `split_id`.
5. The comparison runner passes that same dataset instance to the shared
   training engine once for each model family: LSTM, GRU, and temporal
   Transformer.
6. The engine applies common reproducibility, fitting, early-stopping, and
   evaluation rules. A model builder may define only its neural architecture.
7. The engine evaluates final predictions against the untouched test split and
   computes MAE, MSE, RMSE, and median per-example inference latency.
8. A successful run publishes a content-addressed `.keras` artifact and then
   atomically publishes its JSON manifest. The manifest is the discovery and
   compatibility boundary for later runtime services.

## Component Boundaries

### Demo-data generator

`prediction/demo_data.py` owns deterministic data construction and a thin
`scripts/seed_prediction_demo_data.py` command owns argument parsing and user
output. Generation accepts explicit values rather than reading process-global
randomness or the wall clock.

The generator creates enough consecutive five-minute history for all three
chronological splits to contain complete twelve-step examples. Its occupancy
pattern combines seeded daily and weekly demand, bounded random variation,
weather effects, holidays, and scheduled events. It also creates completed
parking sessions and their allocations so entry, exit, active-session,
returning-vehicle, walking-distance, congestion, and fairness features are
represented. Counts never exceed the configured slot count and all timestamps
are normalized UTC ISO-8601 strings.

Generated RFID values are deterministic synthetic lifecycle identifiers. They
remain inside the lifecycle database boundary and never enter source records,
prepared arrays, logs, manifests, or errors.

### Demo ownership and replacement

Database initialization adds a small `prediction_demo_records` ownership table
containing a dataset key, owned table name, and owned row ID. The table records
only rows created by the generator and has a uniqueness constraint over those
three fields. It deliberately does not infer ownership from timestamps,
identifier prefixes, or data values.

Regeneration uses `BEGIN IMMEDIATE`. It reads the ledger for the requested
dataset key, deletes owned allocations, optimizer runs, sessions, vehicles,
and context samples in foreign-key-safe order, removes the old ledger rows,
then creates and records the replacement rows. Any failure rolls back both the
deletion and insertion. Rows absent from the ownership ledger are never
deleted. All generated sessions are completed, so regeneration cannot disturb
current slot occupancy or active-session invariants.

The command reports aggregate counts and the dataset key, never RFID values or
database row payloads. Repeating a command with the same inputs produces the
same prediction source values, prepared arrays, target timestamps, and
`split_id`; SQLite surrogate IDs need not repeat.

### Training contracts

`prediction/training.py` defines immutable, validated contracts for:

- model family (`lstm`, `gru`, or `transformer`);
- shared training configuration, including seed, epochs, batch size, learning
  rate, early-stopping patience, and compact architecture dimensions;
- evaluation metrics;
- completed training result; and
- stable typed training errors.

Its public entry point accepts a `PreparedDataset`, training configuration, and
artifact directory. It does not accept a database, raw source records,
preprocessing configuration, or independently supplied arrays. This shape
makes the shared dataset boundary enforceable rather than conventional.

The comparison entry point accepts one `PreparedDataset` and an ordered set of
the three model configurations. It invokes the same training engine for each
family and returns results in the fixed order LSTM, GRU, Transformer. Model
families cannot override splitting, scaling, loss, metrics, early-stopping
monitor, or latency methodology.

### TensorFlow boundary

`prediction/architectures.py` lazily imports TensorFlow only when a real model
is built. If it is unavailable, training raises `PredictionTrainingError` with
code `missing_ml_dependency` and an instruction to install the `ml` extra.
Importing any preprocessing, database, demo, or backend module remains safe
without TensorFlow.

The three builders share the input shape
`(dataset.config.lookback_steps, len(dataset.feature_names))` and return one
finite scalar occupancy ratio per example:

- LSTM uses a compact recurrent layer and scalar sigmoid regression head.
- GRU uses the corresponding compact recurrent layer and the same head.
- The temporal Transformer projects features to an embedding dimension, adds
  deterministic positional encoding, applies compact self-attention,
  residual/normalization and feed-forward blocks, pools over time, and uses the
  same scalar sigmoid head.

All models compile with the same optimizer family, learning rate, and MSE loss.
Architecture-specific parameters are limited to capacity fields in the shared
configuration and are recorded in the manifest.

An internal backend protocol allows fast tests to exercise the real orchestration
contract without TensorFlow. It is not a public alternative training API and
cannot receive different arrays or split rules.

## Deterministic Fitting

Before each build, the engine seeds Python, NumPy, and TensorFlow with the
configured integer and requests deterministic TensorFlow operations. Training
uses `dataset.train`, validation uses `dataset.validation`, and `shuffle=False`.
Early stopping monitors validation loss, restores the best weights, and uses a
shared patience rule. Tests ensure the engine never fits or selects against the
test split.

Semantic reproducibility means that identical inputs, configuration, supported
TensorFlow environment, and hardware produce matching predictions within the
documented floating-point tolerance. Cross-version or cross-hardware
byte-identical Keras files are not promised. Inference latency is inherently
observational and is excluded from deterministic identity claims.

## Shared Evaluation

`prediction/evaluation.py` owns framework-independent evaluation after model
prediction. It validates that predictions are a one-dimensional finite vector
with exactly one value per test example and values within `[0, 1]`. Metrics are
computed in NumPy with float64 accumulation:

- MAE is the mean absolute error;
- MSE is the mean squared error; and
- RMSE is the square root of MSE.

Latency measurement performs an unmeasured warm-up, then multiple complete
test-split inference calls with a monotonic nanosecond clock. It reports the
median elapsed milliseconds divided by the number of test examples. Loading,
model construction, compilation, and warm-up are outside the measurement.
The number of measured repetitions is validated and recorded.

The test split is evaluated once per completed training run. Repeated calls
used solely for latency operate on the same frozen test inputs and do not alter
model weights or select hyperparameters.

## Artifact and Manifest Publication

Models use native `.keras` format. A successful publication follows this
sequence:

1. Save the model to a unique staging path inside the destination directory.
2. Compute SHA-256 over the completed staged artifact.
3. Move it to an immutable content-addressed filename based on that digest. If
   the identical artifact already exists, retain the existing file.
4. Serialize the manifest to a temporary sibling file, flush it, and atomically
   replace the stable manifest path.

Only manifests are discovery records. A crash before the final manifest rename
may leave an unreferenced artifact, but cannot advertise a partial or mismatched
model. Garbage collection of unreferenced artifacts is outside this slice.

The versioned manifest contains:

- schema version, model family, artifact format, relative artifact filename,
  and artifact SHA-256;
- dataset `split_id`, ordered feature names, target name, slot count, interval,
  lookback, and horizon;
- training seed and all effective hyperparameters;
- train, validation, and test example counts;
- MAE, MSE, RMSE, inference latency, and measured repetition count;
- TensorFlow and Keras versions; and
- a timezone-aware UTC completion timestamp.

The manifest deliberately excludes source rows, RFID values, prepared arrays,
and scaler values. The dataset `split_id` and feature/geometry contract provide
the compatibility link without duplicating training data.

`prediction/artifacts.py` loads and validates manifests. It rejects unknown
schema versions, paths escaping the artifact directory, invalid hashes,
unsupported model families, non-finite metrics, malformed timestamps, feature
or geometry mismatches, and a caller-supplied expected `split_id` mismatch
before loading TensorFlow model bytes.

## Validation and Failure Handling

Stable `PredictionTrainingError` codes cover:

- `invalid_training_config` for malformed seeds, sizes, rates, epoch counts,
  patience, or latency repetitions;
- `unsupported_model` for names outside the fixed comparison set;
- `missing_ml_dependency` when real training is invoked without TensorFlow;
- `incompatible_dataset` for feature, target, geometry, shape, or split
  contract violations;
- `invalid_prediction` for wrong-shaped, non-finite, or out-of-range model
  outputs;
- `training_failed` for framework fitting failures;
- `artifact_write_failed` for staging or publication failures; and
- `invalid_manifest` or `artifact_mismatch` for unsafe, corrupt, or
  incompatible persisted artifacts.

Errors identify fields and model families but never include input arrays,
source records, generated RFID values, or arbitrary TensorFlow object
representations. Filesystem failures clean temporary manifest and staging
paths when possible. Existing valid manifests remain discoverable unless and
until a replacement manifest has been completely written.

## Testing Strategy

Demo tests use temporary SQLite databases and literal expectations to prove:

- identical generation inputs reproduce source values, prepared arrays,
  timestamps, and `split_id`;
- different seeds change generated feature data;
- reruns do not accumulate records;
- unrelated context, lifecycle, optimizer, and allocation records survive;
- generated occupancy and timestamps respect slot and forecast contracts;
- every aggregate feature family receives representative data; and
- failed generation rolls back to the preceding complete dataset.

Training and evaluation tests use the internal deterministic backend to prove:

- all three model families receive the exact same `PreparedDataset` object;
- trainers expose no raw-source or private-preprocessing path;
- train, validation, and test splits retain their assigned roles;
- seeds, no-shuffle fitting, and early-stopping settings are shared;
- hand-calculated MAE, MSE, and RMSE values are correct;
- malformed predictions and configurations fail with stable codes;
- warm-up is excluded and median per-example latency is calculated correctly;
- artifact hashes and manifests match, publish only after successful saves,
  and reject tampering or incompatible datasets; and
- importing non-ML application paths works without TensorFlow.

When TensorFlow is installed, marked smoke tests build, fit briefly, predict,
save, and reload each real architecture using a tiny deterministic prepared
dataset. Their purpose is integration compatibility, not model quality or
benchmark performance. They are skipped only when the optional dependency is
absent.

Completion requires focused prediction tests, the entire test suite, Ruff, and
`git diff --check` to pass. `progress.md` is updated during the final verified
documentation pass with the then-current focused and full-suite counts; it
must at minimum correct the stale 35/125 preprocessing counts to 72/162.

## Follow-On Work

The next prediction slice will atomically persist completed manifest summaries
to `prediction_runs`, expose predictor comparison and runtime forecast APIs,
select a configured compatible artifact, and provide the deterministic
fallback when no valid trained artifact exists. It will consume the manifest
and `PreparedDataset` compatibility boundaries defined here rather than
loading arbitrary model files or training during an API request.
