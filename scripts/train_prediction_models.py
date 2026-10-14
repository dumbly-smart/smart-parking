"""Train and compare all prediction model families from one prepared dataset."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC
from pathlib import Path

import numpy as np

from backend.app.config import Settings
from backend.app.db import Database
from prediction.data import prepare_prediction_dataset
from prediction.evaluation import evaluate_predictions, measure_inference_latency
from prediction.models import FEATURE_NAMES
from prediction.training import (
    PredictionTrainingError,
    compare_models,
    default_comparison_configs,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url")
    parser.add_argument("--artifact-directory", type=Path, required=True)
    parser.add_argument("--results-directory", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    setting_values = {}
    if args.database_url is not None:
        setting_values["database_url"] = args.database_url
    try:
        settings = Settings(**setting_values)
        database = Database(settings.database_path)
        database.initialize(settings.parking.slots)
        dataset = prepare_prediction_dataset(database.load_prediction_source_data())
        results = compare_models(
            dataset,
            default_comparison_configs(),
            args.artifact_directory,
        )
        database.save_prediction_results(results)
        if args.results_directory is not None:
            _write_results(
                dataset,
                results,
                args.artifact_directory,
                args.results_directory,
                settings.database_url,
            )
    except PredictionTrainingError as error:
        print(f"error: {error.message}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            [
                {
                    "manifest_path": str(result.manifest_path),
                    "metrics": asdict(result.metrics),
                    "model": result.model.value,
                    "split_id": result.split_id,
                }
                for result in results
            ],
            sort_keys=True,
        )
    )
    return 0


def _write_results(
    dataset, results, artifact_directory: Path, results_directory: Path, database_url: str
) -> None:
    """Reload published models, validate their manifests, and emit measured outputs."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from fastapi.testclient import TestClient

    from backend.app.main import create_app
    from prediction.architectures import _require_tensorflow
    from prediction.artifacts import load_manifest

    results_directory.mkdir(parents=True, exist_ok=True)
    figures = results_directory / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    tf = _require_tensorflow()
    predictions_by_model: dict[str, np.ndarray] = {}
    comparison: list[dict[str, object]] = []
    histories: list[dict[str, object]] = []

    occupancy_index = FEATURE_NAMES.index("occupancy_ratio")
    scaler_index = dataset.scaler.feature_indices.index(occupancy_index)
    last_occupancy = (
        dataset.test.inputs[:, -1, occupancy_index] * dataset.scaler.scales[scaler_index]
        + dataset.scaler.means[scaler_index]
    )
    baseline_prediction = np.clip(last_occupancy, 0.0, 1.0)
    baseline_quality = evaluate_predictions(baseline_prediction, dataset.test.targets)
    baseline_latency = measure_inference_latency(
        lambda values: np.clip(
            values[:, -1, occupancy_index] * dataset.scaler.scales[scaler_index]
            + dataset.scaler.means[scaler_index],
            0.0,
            1.0,
        ),
        dataset.test.inputs,
        5,
    )
    comparison.append(
        {
            "model": "persistence_baseline",
            "mae": baseline_quality.mae,
            "mse": baseline_quality.mse,
            "rmse": baseline_quality.rmse,
            "inference_latency_ms": baseline_latency,
            "model_size_bytes": "N/A",
            "manifest_path": "N/A",
        }
    )
    predictions_by_model["persistence_baseline"] = baseline_prediction

    for result in results:
        manifest = load_manifest(result.manifest_path, expected_dataset=dataset)
        model_path = artifact_directory / manifest.artifact_filename
        model = tf.keras.models.load_model(model_path)
        values = np.asarray(model.predict(dataset.test.inputs, verbose=0)).reshape(-1)
        if not np.isfinite(values).all() or np.any((values < 0) | (values > 1)):
            raise PredictionTrainingError(
                "invalid_prediction", f"reloaded {result.model.value} predictions are invalid"
            )
        quality = evaluate_predictions(values, dataset.test.targets)
        predictions_by_model[result.model.value] = values
        comparison.append(
            {
                "model": result.model.value,
                "mae": quality.mae,
                "mse": quality.mse,
                "rmse": quality.rmse,
                "inference_latency_ms": result.metrics.inference_latency_ms,
                "model_size_bytes": model_path.stat().st_size,
                "manifest_path": str(result.manifest_path),
            }
        )
        epochs = max(
            len(result.training_history.get("loss", ())),
            len(result.training_history.get("val_loss", ())),
        )
        history_path = figures / f"{result.model.value}_loss.png"
        if epochs:
            train_loss = result.training_history.get("loss", ())
            validation_loss = result.training_history.get("val_loss", ())
            figure, axis = plt.subplots(figsize=(8, 5), dpi=180)
            axis.plot(range(1, len(train_loss) + 1), train_loss, marker="o", label="Training loss")
            axis.plot(
                range(1, len(validation_loss) + 1),
                validation_loss,
                marker="o",
                label="Validation loss",
            )
            axis.set(
                title=f"{result.model.value.upper()} training and validation loss",
                xlabel="Epoch",
                ylabel="MSE loss",
            )
            axis.legend()
            axis.grid(alpha=0.25)
            figure.tight_layout()
            figure.savefig(history_path)
            plt.close(figure)
            for epoch in range(epochs):
                histories.append(
                    {
                        "model": result.model.value,
                        "epoch": epoch + 1,
                        "training_loss": train_loss[epoch] if epoch < len(train_loss) else "",
                        "validation_loss": validation_loss[epoch]
                        if epoch < len(validation_loss)
                        else "",
                    }
                )

    fields = tuple(comparison[0])
    with (results_directory / "model_comparison.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(comparison)
    api_checks = []
    for model_name in ("lstm", "gru", "transformer"):
        api_settings = Settings(
            database_url=database_url,
            selected_predictor=model_name,
            prediction_artifact_directory=artifact_directory,
        )
        with TestClient(create_app(api_settings)) as client:
            response = client.get("/api/prediction")
        response.raise_for_status()
        forecast = response.json()
        if forecast["model"] != model_name or forecast["fallback_reason"] is not None:
            raise PredictionTrainingError(
                "runtime_inference_failed", f"configured {model_name} predictor used fallback"
            )
        api_checks.append(
            {
                "model": model_name,
                "occupancy_ratio": forecast["occupancy_ratio"],
                "target_at": forecast["target_at"],
            }
        )

    (results_directory / "model_comparison.json").write_text(
        json.dumps(
            {
                "split_id": dataset.split_id,
                "test_examples": int(dataset.test.targets.size),
                "train_examples": int(dataset.train.targets.size),
                "validation_examples": int(dataset.validation.targets.size),
                "results": comparison,
                "prediction_api_checks": api_checks,
                "inference_environment": "CPU/server process; no microcontroller inference was measured",  # noqa: E501
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    with (results_directory / "training_history.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.DictWriter(
            stream, fieldnames=("model", "epoch", "training_loss", "validation_loss")
        )
        writer.writeheader()
        writer.writerows(histories)

    with (results_directory / "test_predictions.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        fields = ("timestamp_utc", "actual_occupancy_ratio", *predictions_by_model)
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for index, timestamp in enumerate(dataset.test.target_timestamps):
            row = {
                "timestamp_utc": timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                "actual_occupancy_ratio": dataset.test.targets[index],
            }
            row.update({name: values[index] for name, values in predictions_by_model.items()})
            writer.writerow(row)

    for metric, label, filename in (
        ("mae", "MAE (occupancy-ratio points)", "mae_comparison.png"),
        ("rmse", "RMSE (occupancy-ratio points)", "rmse_comparison.png"),
        ("inference_latency_ms", "Median latency (ms per prediction)", "latency_comparison.png"),
    ):
        figure, axis = plt.subplots(figsize=(8, 5), dpi=180)
        axis.bar([row["model"] for row in comparison], [row[metric] for row in comparison])
        axis.set(title=f"Prediction model {label.split()[0]} comparison", ylabel=label)
        axis.tick_params(axis="x", rotation=20)
        axis.grid(axis="y", alpha=0.25)
        figure.tight_layout()
        figure.savefig(figures / filename)
        plt.close(figure)

    figure, axis = plt.subplots(figsize=(12, 5), dpi=180)
    timestamps = dataset.test.target_timestamps
    axis.plot(timestamps, dataset.test.targets, label="Actual", linewidth=1.5)
    for name, values in predictions_by_model.items():
        axis.plot(timestamps, values, label=name, linewidth=1.0, alpha=0.8)
    axis.set(
        title="Test-set actual vs predicted occupancy ratio",
        xlabel="Target time (UTC)",
        ylabel="Occupancy ratio",
    )
    axis.set_ylim(0, 1)
    axis.legend(ncol=2)
    axis.grid(alpha=0.25)
    figure.autofmt_xdate()
    figure.tight_layout()
    figure.savefig(figures / "actual_vs_predicted.png")
    plt.close(figure)

    errors = np.concatenate(
        [values - dataset.test.targets for values in predictions_by_model.values()]
    )
    figure, axis = plt.subplots(figsize=(8, 5), dpi=180)
    axis.hist(errors, bins=30, edgecolor="white")
    axis.set(
        title="Test-set prediction error distribution",
        xlabel="Prediction error (predicted - actual occupancy ratio)",
        ylabel="Count",
    )
    axis.grid(axis="y", alpha=0.25)
    figure.tight_layout()
    figure.savefig(figures / "prediction_error_distribution.png")
    plt.close(figure)


if __name__ == "__main__":
    raise SystemExit(main())
