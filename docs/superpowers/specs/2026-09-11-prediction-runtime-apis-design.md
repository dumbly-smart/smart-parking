# Prediction Persistence and Runtime APIs Design

## Scope

This slice persists completed predictor-comparison results, exposes their
privacy-safe summaries, and serves a five-minute occupancy forecast. It keeps
`PreparedDataset` as the sole training boundary: runtime source aggregation
and feature-window construction live in `prediction.data`; no route, service,
or model loader may create an alternate split, scaler, or feature order.

## Compatibility and artifacts

The current source snapshot is prepared once per request. `split_id` is
strengthened to hash the canonical, privacy-preserving feature timeline as
well as the existing geometry and time bounds, so changed source values cannot
silently reuse a model. It never serializes RFID identifiers.

Artifact manifests move to schema version 2 and include the frozen continuous
feature scaler metadata already owned by `PreparedDataset`. This is model
input-contract metadata, not source data, and contains only feature indices,
finite means, and positive scales. The loader validates manifest schema,
feature contract, five-minute geometry, split ID, scaler, contained artifact
path, and content hash before TensorFlow is imported or model bytes are
loaded. Schema-v1 manifests can be parsed for historical comparison display
but are not runtime-compatible.

## Persistence and comparison API

`Database.save_prediction_results()` receives completed `TrainingResult`
objects only after their manifests have passed `load_manifest()` validation.
It serializes a whitelist summary of each manifest (never a path outside the
configured artifact directory and never source rows or RFID data) and inserts
all comparison rows in one SQLite transaction. A failing row leaves none of
the comparison rows visible. `GET /api/benchmarks/predictors` returns typed
persisted summaries in newest-first order.

The training CLI prepares the snapshot once, trains the three models through
the existing comparison engine, validates each manifest, and atomically saves
the completed comparison. The comparison engine itself still accepts only one
`PreparedDataset` and has no database dependency.

## Runtime forecast API

`PredictionService` prepares the current snapshot once and asks the shared
data module for the latest complete twelve-bucket input window and its next
five-minute UTC target timestamp. The helper requires the target timestamp to
be exactly five-minute aligned, uses the existing feature order, and applies
only the scaler from the selected, compatible manifest. It does not create a
training, validation, or test split.

For configured LSTM, GRU, or Transformer selection, the service selects the
latest persisted row for that family, validates the referenced manifest and
artifact against the freshly prepared dataset, then lazily loads the Keras
model and validates its one-element finite `[0, 1]` output. Artifact failures,
incompatibility, missing ML support, missing history, and invalid model output
never leak implementation details and fall back to a deterministic baseline:
the latest observed occupancy ratio, clamped to `[0, 1]`. The response exposes
the selected `model` (`baseline` when falling back), `occupancy_ratio`,
`target_at`, and an optional stable `fallback_reason`; it exposes no RFID,
source rows, model paths, or manifest payloads.

`GET /api/prediction` is cacheable only within its target five-minute bucket;
the service stores one immutable response per target timestamp and recomputes
when the bucket changes. No model is trained within an API request.

## Error handling and tests

Runtime failures are deliberate degradation, not HTTP 500s. Stable fallback
reasons distinguish `no_compatible_artifact`, `invalid_artifact`,
`missing_ml_dependency`, `insufficient_history`, and `invalid_prediction`
without reflecting exception text. Database persistence failures remain typed
and atomic.

Tests are added first and prove: transaction rollback; only validated,
non-RFID manifests persist; comparison output is typed; schema-v2 scaler and
timeline identities reject tampering; runtime validates split, feature order,
geometry, scaler, hash, and model output before loading; cache behavior stays
five-minute aligned; fallback is deterministic; and the HTTP APIs never
return RFID data. Existing TensorFlow-independent tests use narrow fakes at
the file-loading boundary; real TensorFlow remains optional.
