# Smart Parking

Five-slot smart parking prototype with a FastAPI/SQLite server and a fully
hardware-independent demo path. The remaining optimizer, vision, prediction,
dashboard, and firmware milestones are tracked in `progress.md`.

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
database and idempotently seeds the five slots from `config/parking.yaml`.

Copy `.env.example` to `.env` to override local configuration. Hardware mode
requires both `SMART_PARKING_MODE=hardware` and
`SMART_PARKING_HARDWARE_ENABLED=true`, preventing accidental physical-mode
startup. Local databases, secrets, calibrated ROIs, datasets, and generated
model artifacts are ignored by Git.

## Allocation comparison

`POST /api/allocation/run` accepts five normalized slot candidates and an
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

Representative status response (the real response always contains slots 1
through 5):

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
