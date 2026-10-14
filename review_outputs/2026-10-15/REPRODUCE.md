# Reproduce the review experiments

Run from the repository root with the project's `.venv` or another Python 3.11+ environment.

```bash
python -m pip install -e '.[dev,ml]'
make review-dataset
make review-ml
make review-package-models
make review-optimizers
make review-report
```

`make review` runs all stages in order, including a SHA-256-verified ZIP of the
three trained models and their manifests at
`ml_results/prediction_model_artifacts.zip`. Dataset generation uses only
`review_outputs/2026-10-15/dataset/review.db`; it does not connect to the
application's configured database. Re-running it replaces rows owned by the
review dataset key in that dedicated database.

Model weights are written under the ignored `artifacts/prediction/` directory.
CSV, JSON, PNG figures, and the dataset ZIP are written under
`review_outputs/2026-10-15/`. The dataset generator uses seed `20260908`, starts
at `2026-08-01T00:00:00Z`, and emits fourteen days at five-minute intervals.
The optimizer runner uses 120 scenarios, three repeat seeds per scenario, and
30 iterations per heuristic. It reads the same objective weights from
`config/parking.yaml` as the application.

The ML training command requires TensorFlow. Inference latency is measured on
the current server CPU; the project does not measure ESP32 performance or power
consumption. All generated parking observations are simulated.
