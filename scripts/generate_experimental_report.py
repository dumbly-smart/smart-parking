"""Assemble the submission report from executed dataset and experiment outputs."""

# ruff: noqa: E501 -- generated Markdown paragraphs and tables stay as single-line literals.

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
        "Generated from local executed outputs. All dataset observations are synthetic simulations.",
        "",
        "## Dataset",
        "",
    ]
    if dataset:
        lines.extend(
            [
                f"The exported feature timeline contains {dataset['records']['feature_timeline']:,} five-minute buckets and {dataset['feature_count']} model features over {dataset['time_coverage_utc']['start']} to {dataset['time_coverage_utc']['end']}. The raw export contains {dataset['records']['raw_observations']:,} privacy-safe source records. Seed: `{dataset['random_seed']}`.",
                "Google Drive dataset ZIP: "
                f"[download]({DATASET_DRIVE_URL}) (read-only access for `vit.ac.in`).",
                "",
                f"Training sequences: {dataset['preprocessing']['sequence_counts']}. Continuous variables are standardized using training data only. The unchanged prediction contract uses a 12-bucket lookback and next-bucket target.",
                "",
                "The generator is simulated. It does not represent measured weather, site demand, camera accuracy, physical waiting times, or parking throughput.",
            ]
        )
    else:
        lines.append("Dataset export is unavailable; run `make review-dataset`.")
    lines.extend(["", "## Prediction experiments", ""])
    if models:
        lines.extend(
            [
                "All models share the same prepared dataset and untouched chronological test split. The persistence baseline predicts that the most recent occupancy ratio continues for one interval. Latency is measured per prediction in this server process.",
                "",
                "| Model | MAE | MSE | RMSE | Median latency (ms) | Model size (bytes) |",
                "| --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in models:
            lines.append(
                f"| {row['model']} | {float(row['mae']):.6f} | {float(row['mse']):.6f} | {float(row['rmse']):.6f} | {float(row['inference_latency_ms']):.6f} | {row['model_size_bytes']} |"
            )
        best = min(models, key=lambda row: float(row["mae"]))
        lines.extend(
            [
                "",
                f"Lowest measured MAE: **{best['model']}** ({float(best['mae']):.6f}). This ranking applies to the generated data and this execution environment only.",
                "",
                "Artifacts were reloaded and hash/manifest checked. The configured `/api/prediction` endpoint returned neural predictions without fallback for each family. These are server-side results; no ESP32 or other microcontroller inference was measured.",
                "Model ZIP with weights, manifests, results, and checksums: "
                f"[download]({MODEL_ARTIFACT_DRIVE_URL}) (read-only access for `vit.ac.in`).",
            ]
        )
    else:
        lines.append(
            "Neural model training results are unavailable. Run `make review-ml`; do not infer neural-model quality from unit tests or the deterministic runtime fallback."
        )
    lines.extend(["", "## Allocation optimizer experiments", ""])
    if algorithms and optimizer:
        lines.extend(
            [
                f"The benchmark ran {optimizer['scenario_count']} distinct scenarios with {optimizer['repeated_seeds_per_scenario']} seeded repetitions. It used the configured weights `{json.dumps(optimizer['weights'], sort_keys=True)}` and 30 iterations per heuristic. {optimizer['full_capacity_rejections']} full-capacity attempts were recorded separately (60 per policy/reference in this run).",
                "",
                "| Algorithm/reference | Successful runs | Success rate | Mean cost | Runtime mean / median / SD (ms) | Mean optimality gap | Invalid assignments |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in algorithms:
            lines.append(
                f"| {row['algorithm']} | {row['successful_runs']} | {float(row['success_rate']):.3f} | {float(row['mean_cost']):.6f} | {float(row['mean_runtime_ms']):.6f} / {float(row['median_runtime_ms']):.6f} / {float(row['std_runtime_ms']):.6f} | {float(row['mean_optimality_gap']):.6f} | {row['invalid_assignments']} |"
            )
        best = min(algorithms, key=lambda row: float(row["mean_cost"]))
        lines.extend(
            [
                "",
                f"Lowest mean objective cost among successful policies: **{best['algorithm']}** ({float(best['mean_cost']):.6f}). Exhaustive enumeration is the exact single-slot optimum for each small scenario; first-available is a simple deterministic selection policy, not FCFS queue scheduling.",
                "",
                "These runs measure a simulated one-slot objective and Python software runtime. They do not measure physical parking throughput or real-world waiting time. Heuristic search is not expected to beat exact enumeration for five candidates.",
            ]
        )
    else:
        lines.append("Optimizer benchmarks are unavailable; run `make review-optimizers`.")
    lines.extend(
        [
            "",
            "## Hardware status and engineering estimates",
            "",
            "The user reports that the assembled tabletop hardware works. This is a qualitative user report; no post-rewire trial logs, operator trial count, or quantitative results were captured. Earlier local RC522 SPI probes returned invalid values before the user reported the successful check. These earlier probes do not establish current hardware failure, and the later report does not establish a measured success rate.",
            "",
            "The following are rough engineering planning estimates, not hardware measurements or simulated benchmark results. Success-rate and latency ranges are low-confidence analyst assumptions for close-range tabletop use on a stable local Wi-Fi network. Replace them with trial data before making performance claims. Component values use the firmware and manufacturer specifications where available.",
            "",
            "| Quantity | Rough estimate | Basis and limitation |",
            "| --- | ---: | --- |",
            "| RFID successful reads per close, aligned tap | 90-99% (very low confidence) | Assumes a supported tag within about 20 mm, stable 3.3 V, and no nearby metal. MFRC522 specifies up to 50 mm depending on antenna tuning; this is not a success-rate guarantee ([NXP datasheet](https://www.nxp.com/docs/en/data-sheet/MFRC522.pdf)). |",
            "| API entry/exit transaction success on stable LAN | 98-99.5% (very low confidence) | Planning assumption for healthy Wi-Fi and backend; no post-rewire trial series was captured. |",
            "| Camera capture success on stable power/Wi-Fi | 95-99% (very low confidence) | Planning assumption only; no physical capture series or dropped-frame count. |",
            "| LED correctness with known slot state | 95-100% (very low confidence) | Assumes correct wiring/polarity and status refresh; no expected-versus-observed trials. |",
            "| Entry/exit latency, tag detection to accepted response | 0.2-1.0 s (low confidence) | Order-of-magnitude estimate for one local request and SQLite transaction. Firmware's 3.5 s HTTP timeout is a failure limit, not expected latency. |",
            "| Wi-Fi recovery after AP is available | 5-15 s (low confidence) | Firmware retries every 5 s; range allows up to 10 s association/DHCP after retry. |",
            "| Servo command delay after RFID detection | 0.2-1.0 s (low confidence) | Assumes one healthy local API round trip; excludes mechanical travel. |",
            "| SG90 10°→85° travel | 0.13-0.50 s (very low confidence) | Nominal ideal is 125 ms from 75° x 0.1 s/60° at 4.8 V; upper range adds load/settling allowance ([TowerPro](https://towerpro.com.tw/product/sg90-7/)). |",
            "| OV2640 frame capture latency | 0.10-0.50 s (very low confidence) | Planning range for one SVGA-class JPEG with PSRAM; exposure and board variance affect timing. No physical capture log. |",
            "| Backend five-ROI processing latency | 0.01-0.10 s (very low confidence) | Planning range for one frame on local host; excludes capture/transfer/queue delay. |",
            "| Controller free heap | Measured historical mean 274,069 bytes (n=8) | Captured serial telemetry before the user's later report; median 292,240, SD 26,019, p95 293,416 bytes. This is measured, not an estimate. |",
            "| Controller + reader + OLED + LEDs input current, servo excluded | 0.15-0.40 A at 5 V (very low confidence) | Budget estimate from ESP32 active Wi-Fi current plus peripheral allowance; regulator and duty cycle vary ([Espressif datasheet](https://documentation.espressif.com/esp32_datasheet_en.html)). |",
            "| AI-Thinker ESP32-CAM input current | About 0.18 A at 5 V; up to 0.31 A with flash at maximum | Manufacturer specification, not measured on this board ([Ai-Thinker specification](https://d229kd5ey79jzj.cloudfront.net/1205/ESP32-CAM%20Product%20Specification.pdf)). |",
            "| SG90 servo supply current | 0.5-2.0 A (very low confidence) | Manufacturer product page notes this range; exact servo/load is unknown. Use separate regulated supply ([TowerPro](https://towerpro.com.tw/product/sg90-7/)). |",
            "| Camera occupancy accuracy | Not estimated | Requires manually labeled real-scene images; synthetic frames cannot support accuracy claims. |",
            "",
            "The probability and performance ranges above are assumptions for planning, not confidence intervals from data. Captured physical free-heap samples and API responses remain identified separately as measured observations in `output/hardware/`; simulated API and optimizer runtimes remain software-only results. Current estimates are per separate rail and must not be added as if measured simultaneously.",
            "",
        ]
    )
    lines.extend(
        [
            "",
            "## Reproduction and outputs",
            "",
            "Run `make review` to regenerate the dataset, ML artifacts and metrics, verified model ZIP, optimizer tables and figures, and this report. See `REPRODUCE.md` for individual commands.",
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
