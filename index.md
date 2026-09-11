# Smart Parking

Smart Parking is a hardware-independent smart parking prototype with a
FastAPI/SQLite backend, deterministic occupancy demos, optimizer comparisons,
and privacy-preserving occupancy prediction.

## Start here

- [README](README.md) — installation, API examples, and local commands
- [Architecture](architecture.md) — system components and data flow
- [Decisions](decisions.md) — recorded architecture decisions
- [Progress](progress.md) — milestone status and verification evidence
- [Original design](2026-09-03-smart-parking-design.md) — project design

## Architecture at a glance

```text
Camera / RFID clients
          |
       FastAPI
          |
   SQLite persistence
      /         \
 Allocation     Lifecycle
      \         /
       Prediction
          |
  PreparedDataset
          |
 LSTM · GRU · Transformer
```

The backend supports configurable parking slots, atomic parking lifecycle
operations, deterministic camera occupancy detection, and optimizer-backed
slot allocation. RFID identifiers remain inside the lifecycle boundary.

## Prediction workflow

1. Seed deterministic five-minute demo history with
   `scripts.seed_prediction_demo_data`.
2. Build one immutable `PreparedDataset` using the shared preprocessing
   contract.
3. Train and compare LSTM, GRU, and temporal Transformer models with
   `scripts.train_prediction_models`.
4. Publish content-addressed model artifacts and validated JSON manifests.

All models use the same chronological 70/15/15 split, twelve-step history, and
next-five-minute occupancy target. GRU is the current affordable deployment
candidate; final selection should use measured quality and latency on the target
machine.

## Quick start

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
make test
make lint
make run
```

The API is available at `http://127.0.0.1:8000`; check `/health` after startup.
The optional TensorFlow dependency is required for real model training:

```bash
.venv/bin/python -m pip install -e '.[ml]'
```

## Current status

Shared prediction preprocessing, deterministic demo data, model comparison,
evaluation, and artifact manifests are implemented. The current verification
result is **209 tests passed**, with three TensorFlow-optional tests skipped in
environments where TensorFlow is not installed. Prediction persistence and
runtime/comparison APIs remain future work; see [progress.md](progress.md).
