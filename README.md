# Smart Parking

Smart parking prototype with a FastAPI/SQLite server and a fully
hardware-independent demo path. The committed configuration models the current
five-slot rig, while the backend supports any non-empty configured slot set.
The remaining prediction, dashboard, and firmware milestones are tracked in
`progress.md`.

## Backend foundation

Python 3.11 or newer is required. Create an isolated environment and install
the project:

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Run verification and start the development server:

```bash
make test
make lint
make run
```

Open `http://127.0.0.1:8000/health`. The first startup creates the local SQLite
database and idempotently seeds every slot from `config/parking.yaml`.

Copy `.env.example` to `.env` to override local configuration. Hardware mode
requires both `SMART_PARKING_MODE=hardware` and
`SMART_PARKING_HARDWARE_ENABLED=true`, preventing accidental physical-mode
startup. Local databases, secrets, calibrated ROIs, datasets, and generated
model artifacts are ignored by Git.

## Allocation comparison

`POST /api/allocation/run` accepts one or more normalized slot candidates and an
`algorithm` value of `ga`, `pso`, `aco`, or `all`. Every algorithm excludes
occupied candidates and uses the same configurable weighted objective. Runs
are persisted and available from `GET /api/benchmarks/optimizers`; supply a
fixed `seed` to reproduce the semantic result.

## Parking lifecycle API

Entry and exit use persistent idempotency keys, so RFID controllers may safely
retry requests after a timeout or lost response. Keys are unique across both
operation types.

```bash
curl -X POST http://127.0.0.1:8000/api/vehicle/entry \
  -H 'Content-Type: application/json' \
  -d '{"rfid_uid":"04-A1-B2-C3","idempotency_key":"entry-0001"}'

curl http://127.0.0.1:8000/api/parking/status

curl -X POST http://127.0.0.1:8000/api/vehicle/exit \
  -H 'Content-Type: application/json' \
  -d '{"rfid_uid":"04-A1-B2-C3","idempotency_key":"exit-0001"}'
```

Representative entry response:

```json
{
  "session_id": 1,
  "rfid_uid": "04-A1-B2-C3",
  "slot_id": 1,
  "slot_name": "S1",
  "optimizer": "ga",
  "allocation_cost": 0.07,
  "entered_at": "2026-09-04T10:00:00.000Z",
  "gate_action": "open"
}
```

Representative status response (the real response contains every configured
slot in configuration order):

```json
{
  "slots": [
    {
      "id": 1,
      "name": "S1",
      "walking_distance": 0.2,
      "zone": "north",
      "occupied": true,
      "updated_at": "2026-09-04T10:00:00.000Z",
      "active_session_id": 1,
      "rfid_uid": "04-A1-B2-C3"
    }
  ]
}
```

Representative exit response:

```json
{
  "session_id": 1,
  "rfid_uid": "04-A1-B2-C3",
  "slot_id": 1,
  "slot_name": "S1",
  "exited_at": "2026-09-04T11:00:00.000Z",
  "gate_action": "open"
}
```

A successful entry assigns only a currently free slot and returns
`gate_action: "open"` after the session, allocation, optimizer result, and slot
state commit atomically. Exit closes that session and releases the same slot.
Expected lifecycle conflicts return HTTP 409 with a stable `detail.code`,
including `no_available_slot`, `vehicle_already_parked`,
`vehicle_not_parked`, and `idempotency_conflict`.

## Camera occupancy API

`POST /api/camera/occupancy` accepts a JPEG frame, crops one configured ROI per
parking slot, and runs a deterministic edge-density heuristic. The committed
`config/rois.example.json` matches the five demo slots. For a fixed physical
camera, copy it to the ignored `config/rois.json`, calibrate each pixel
rectangle, and set `SMART_PARKING_ROI_CONFIG_PATH=config/rois.json`.

```bash
curl -X POST http://127.0.0.1:8000/api/camera/occupancy \
  -F 'image=@frame.jpg;type=image/jpeg'
```

The response contains one result per configured slot in parking-configuration
order. A confident state change must appear for three consecutive demo frames
before it is persisted; pending, uncertain, unchanged, and lifecycle-blocked
observations create no occupancy event. The upload limit defaults to 5 MiB and
can be changed with `SMART_PARKING_CAMERA_MAX_IMAGE_BYTES`.

The heuristic is a deterministic baseline for demos and calibration, not a
production-grade classifier. Its edge threshold, confidence threshold, and
smoothing count are configured in the ROI JSON. A later CNN detector can use
the same service contract without changing the camera API.

## Prediction preprocessing

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

## Prediction demo data and model comparison

Seed fourteen days of deterministic five-minute history into an initialized
SQLite database:

```bash
.venv/bin/python -m scripts.seed_prediction_demo_data \
  --database-url sqlite:///./data/parking.db \
  --dataset-key prediction-demo \
  --seed 20260908 \
  --days 14
```

Rerunning the command replaces only rows owned by that dataset key. Unrelated
parking records are preserved, and generated RFID identifiers remain inside
the lifecycle database boundary.

Install the optional ML dependency and train all three model families:

```bash
pip install -e '.[ml]'
.venv/bin/python -m scripts.train_prediction_models \
  --database-url sqlite:///./data/parking.db \
  --artifact-directory artifacts/prediction
```

The database snapshot is prepared exactly once. LSTM, GRU, and temporal
Transformer trainers receive the same immutable `PreparedDataset` and
`split_id`; they cannot perform private preprocessing or splitting. Every run
uses shared fitting rules and reports MAE, MSE, RMSE, and median per-example
inference latency on the untouched test split.

Each model is saved as a content-addressed `.keras` file. Its atomically
published JSON manifest records the artifact digest, data contract,
hyperparameters, split sizes, framework versions, and metrics. Later runtime
services must validate the manifest and `split_id` before loading the artifact.

GRU is the recommended affordable deployment candidate because it has fewer
gates than LSTM and far less attention overhead than the Transformer for this
short twelve-step history. Final selection should still use the measured
quality and latency report produced on the target machine.
