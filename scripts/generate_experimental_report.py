"""Assemble the submission report from executed dataset and experiment outputs."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

ROOT = Path("review_outputs/2026-10-15")
DATASET_DRIVE_URL = (
    "https://drive.google.com/file/d/1-bgCGNuCgbhWTbKyxnMlLpOQH1s3lxSZ/view?usp=drivesdk"
)
MODEL_ARTIFACT_DRIVE_URL = (
    "https://drive.google.com/file/d/1I1ECMeYlJT9-oop4Bh-Qedgti9Kds6lj/view?usp=drivesdk"
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def generate(root: Path) -> None:
    dataset_path = root / "dataset" / "dataset_metadata.json"
    optimizer_path = root / "optimization_results" / "optimizer_summary.json"
    dataset = (
        json.loads(dataset_path.read_text(encoding="utf-8")) if dataset_path.exists() else None
    )
    optimizer = (
        json.loads(optimizer_path.read_text(encoding="utf-8")) if optimizer_path.exists() else None
    )
    models = _read_csv(root / "ml_results" / "model_comparison.csv")
    algorithms = _read_csv(root / "optimization_results" / "optimizer_comparison.csv")

    lines = [
        "# Experimental report — Smart Parking review",
        "",
        "Generated from local executed outputs. All dataset observations are synthetic simulations.",  # noqa: E501
        "",
        "## Dataset",
        "",
    ]
    if dataset:
        lines.extend(
            [
                f"The exported feature timeline contains {dataset['records']['feature_timeline']:,} five-minute buckets and {dataset['feature_count']} model features over {dataset['time_coverage_utc']['start']} to {dataset['time_coverage_utc']['end']}. The raw export contains {dataset['records']['raw_observations']:,} privacy-safe source records. Seed: `{dataset['random_seed']}`.",  # noqa: E501
                "Google Drive dataset ZIP: "
                f"[download]({DATASET_DRIVE_URL}) (read-only access for `vit.ac.in`).",
                "",
                f"Training sequences: {dataset['preprocessing']['sequence_counts']}. Continuous variables are standardized using training data only. The unchanged prediction contract uses a 12-bucket lookback and next-bucket target.",  # noqa: E501
                "",
                "The generator is simulated. It does not represent measured weather, site demand, camera accuracy, physical waiting times, or parking throughput.",  # noqa: E501
            ]
        )
    else:
        lines.append("Dataset export is unavailable; run `make review-dataset`.")
    lines.extend(["", "## Prediction experiments", ""])
    if models:
        lines.extend(
            [
                "All models share the same prepared dataset and untouched chronological test split. The persistence baseline predicts that the most recent occupancy ratio continues for one interval. Latency is measured per prediction in this server process.",  # noqa: E501
                "",
                "| Model | MAE | MSE | RMSE | Median latency (ms) | Model size (bytes) |",
                "| --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in models:
            lines.append(
                f"| {row['model']} | {float(row['mae']):.6f} | {float(row['mse']):.6f} | {float(row['rmse']):.6f} | {float(row['inference_latency_ms']):.6f} | {row['model_size_bytes']} |"  # noqa: E501
            )
        best = min(models, key=lambda row: float(row["mae"]))
        lines.extend(
            [
                "",
                f"Lowest measured MAE: **{best['model']}** ({float(best['mae']):.6f}). This ranking applies to the generated data and this execution environment only.",  # noqa: E501
                "",
                "Artifacts were reloaded and hash/manifest checked. The configured `/api/prediction` endpoint returned neural predictions without fallback for each family. These are server-side results; no ESP32 or other microcontroller inference was measured.",  # noqa: E501
                "Model ZIP with weights, manifests, results, and checksums: "
                f"[download]({MODEL_ARTIFACT_DRIVE_URL}) (read-only access for `vit.ac.in`).",
            ]
        )
    else:
        lines.append(
            "Neural model training results are unavailable. Run `make review-ml`; do not infer neural-model quality from unit tests or the deterministic runtime fallback."  # noqa: E501
        )
    lines.extend(["", "## Allocation optimizer experiments", ""])
    if algorithms and optimizer:
        lines.extend(
            [
                f"The benchmark ran {optimizer['scenario_count']} distinct scenarios with {optimizer['repeated_seeds_per_scenario']} seeded repetitions. It used the configured weights `{json.dumps(optimizer['weights'], sort_keys=True)}` and 30 iterations per heuristic. {optimizer['full_capacity_rejections']} full-capacity attempts were recorded separately (60 per policy/reference in this run).",  # noqa: E501
                "",
                "| Algorithm/reference | Successful runs | Success rate | Mean cost | Runtime mean / median / SD (ms) | Mean optimality gap | Invalid assignments |",  # noqa: E501
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in algorithms:
            lines.append(
                f"| {row['algorithm']} | {row['successful_runs']} | {float(row['success_rate']):.3f} | {float(row['mean_cost']):.6f} | {float(row['mean_runtime_ms']):.6f} / {float(row['median_runtime_ms']):.6f} / {float(row['std_runtime_ms']):.6f} | {float(row['mean_optimality_gap']):.6f} | {row['invalid_assignments']} |"  # noqa: E501
            )
        best = min(algorithms, key=lambda row: float(row["mean_cost"]))
        lines.extend(
            [
                "",
                f"Lowest mean objective cost among successful policies: **{best['algorithm']}** ({float(best['mean_cost']):.6f}). Exhaustive enumeration is the exact single-slot optimum for each small scenario; first-available is a simple deterministic selection policy, not FCFS queue scheduling.",  # noqa: E501
                "",
                "These runs measure a simulated one-slot objective and Python software runtime. They do not measure physical parking throughput or real-world waiting time. Heuristic search is not expected to beat exact enumeration for five candidates.",  # noqa: E501
            ]
        )
    else:
        lines.append("Optimizer benchmarks are unavailable; run `make review-optimizers`.")
    lines.extend(
        [
            "",
            "## Reproduction and outputs",
            "",
            "Run `make review` to regenerate the dataset, ML artifacts and metrics, verified model ZIP, optimizer tables and figures, and this report. See `REPRODUCE.md` for individual commands.",  # noqa: E501
            "",
        ]
    )
    (root / "EXPERIMENTAL_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=ROOT)
    args = parser.parse_args()
    generate(args.output_root)
    print(args.output_root / "EXPERIMENTAL_REPORT.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
