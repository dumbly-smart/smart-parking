# Smart Parking

Smart Parking is a hardware-independent smart parking prototype with a FastAPI/SQLite backend, RFID session management, optimizer comparisons, and occupancy forecasting. Slot occupancy is derived from confirmed entry and exit transactions.

## Start here

- [README](README.md) — installation, API examples, and local commands
- [Architecture](architecture.md) — components and data flow
- [Decisions](decisions.md) — recorded architecture decisions
- [Progress](progress.md) — milestones and verification evidence
- [Final report](output/final_submission/Smart_Parking_Final_Report.pdf)

## Architecture at a glance

```text
RFID tag -> ESP32 controller -> FastAPI -> SQLite
                                  |           |
                       Allocation and prediction
                                  |
                         3D dashboard and LEDs
```

The controller sends idempotent entry and exit requests. The server maintains active sessions and slot state, while the dashboard visualizes committed parking events.

## Prediction workflow

1. Seed deterministic five-minute demo history with `scripts.seed_prediction_demo_data`.
2. Build one immutable `PreparedDataset` using the shared preprocessing contract.
3. Train and compare LSTM, GRU, and temporal Transformer models with `scripts.train_prediction_models`.
4. Publish content-addressed model artifacts and validated JSON manifests.

All models use the same chronological 70/15/15 split, twelve-step history, and next-five-minute occupancy target.

## Quick start

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
make test
make lint
make run
```
