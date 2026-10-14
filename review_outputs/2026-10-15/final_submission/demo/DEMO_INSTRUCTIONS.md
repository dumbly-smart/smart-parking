# Final review demonstration

The physical boards are not available in the current validation environment. Use the software demonstration below; it exercises the existing backend and labeled simulated inputs, not physical RFID, camera or gate hardware.

## Start and demonstrate

From the prepared project workspace, copy the already-generated review database
so the demo cannot modify the original measured experiment data. In terminal 1:

```sh
mkdir -p data
cp review_outputs/2026-10-15/dataset/review.db data/final-review-demo.db
SMART_PARKING_DATABASE_URL=sqlite:///data/final-review-demo.db SMART_PARKING_SELECTED_PREDICTOR=gru python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Expected startup: Uvicorn reports that the application is ready. Open `http://127.0.0.1:8000/` for the dashboard and `http://127.0.0.1:8000/health` for health status.

In terminal 2:

```sh
python -m scripts.run_simulated_demo --base-url http://127.0.0.1:8000
```

The copied database contains the generated timeline and trained model-run manifests; the model files are in the existing ignored `artifacts/prediction/` directory. The demo submits labeled simulated camera frames, one simulated vehicle lifecycle, optimizer comparison and a forecast request. It prints a compact JSON summary with three processed frames, an entry slot, current occupancy, three optimizer results, and forecast output. Verified output returned `model: gru`, `fallback_reason: null`, and a finite occupancy ratio. The command supplies generated JPEGs and a simulator RFID value; it does not interact with physical devices. Refresh the dashboard to view persisted status. If the GRU artifacts are absent or fail compatibility checks, the API returns the safe baseline; do not present that response as neural inference.

This no-retraining command assumes the prepared workspace retains `dataset/review.db` and `artifacts/prediction/` from the completed experiments. Use the Drive archives/reproduction guide to restore them on a clean checkout.

Present model and optimizer evidence from `ml_results/model_comparison.csv`, `optimization_results/optimizer_comparison.csv` and the corresponding `figures/` directories. Models are already trained; the review does not require retraining.

For a physical demonstration after wiring and local configuration, follow `hardware/firmware.md`. Set a local-only `local_config.h`, keep the servo arm unloaded during first tests, start the local backend on the same LAN, and configure camera/backend URLs. Do not expose the unauthenticated hardware endpoints to the public internet.
