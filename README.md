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

## Demo parking lifecycle

Start the server with `make run`, then simulate a vehicle arriving:

```bash
curl -sS -X POST http://127.0.0.1:8000/api/vehicle/entry \
  -H 'Content-Type: application/json' \
  -d '{"rfid_uid":"04-A1-B2-C3","idempotency_key":"entry-demo-001"}'
```

Inspect the five slots and the active vehicle assignment:

```bash
curl -sS http://127.0.0.1:8000/api/parking/status
```

Simulate the same vehicle leaving:

```bash
curl -sS -X POST http://127.0.0.1:8000/api/vehicle/exit \
  -H 'Content-Type: application/json' \
  -d '{"rfid_uid":"04-A1-B2-C3","idempotency_key":"exit-demo-001"}'
```

Each entry or exit needs a non-empty operation-specific idempotency key.
Repeating an identical request with the same key safely replays the original
result; use fresh entry and exit keys for every new visit. Expected lifecycle
conflicts return HTTP 409 with a stable `detail.code`, such as
`no_available_slot`, `vehicle_already_parked`, `vehicle_not_parked`, or
`idempotency_conflict`.
