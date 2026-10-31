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
        "Generated from local executed outputs. Forecasting observations are synthetic; optimizer scenarios come from parking allocations captured during an executed SUMO/TraCI run.",
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
                "The generator is simulated. It does not represent measured weather, site demand, physical waiting times, or parking throughput.",
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
                f"The benchmark captured {optimizer['scenario_count']} SUMO-observed parking allocation states from TraCI arrivals, then ran each optimizer with {optimizer['repeated_seeds_per_scenario']} repeat seeds per observed state. It used the configured weights `{json.dumps(optimizer['weights'], sort_keys=True)}`; GA, PSO, and ACO used 30 iterations, while NSGA-II used population {optimizer['nsga2_parameters']['population_size']}, {optimizer['nsga2_parameters']['generations']} generations, crossover {optimizer['nsga2_parameters']['crossover_probability']:.2f}, and mutation {optimizer['nsga2_parameters']['mutation_probability']:.2f}. SUMO {optimizer['sumo_version']} used seed {optimizer['sumo_seed']} and {optimizer['sumo_step_length_seconds']:.2f} second steps; captured arrivals spanned simulation seconds {optimizer['observed_simulation_start']:.2f} to {optimizer['observed_simulation_end']:.2f}. Configuration, network, and route SHA-256 hashes are recorded in `optimization_results/optimizer_summary.json`. Across the compared runs, {optimizer['full_capacity_rejections']} full-capacity attempts were observed. Candidate snapshots and their objective values are preserved in `optimization_results/{optimizer['scenario_evidence_file']}`.",
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
                f"Lowest mean objective cost among successful policies: **{best['algorithm']}** ({float(best['mean_cost']):.6f}). Exhaustive enumeration is the exact single-slot optimum for each {optimizer['candidate_capacity']:,}-candidate observed state; first-available is a simple deterministic selection policy, not FCFS queue scheduling.",
                "",
                "These are measured optimizer outcomes and Python runtimes from the recorded SUMO execution. Each case uses the live allocation request captured at an actual simulated parking admission, including its occupied slots, zone congestion, configured bay distances, and per-identity fairness history; exact search supplies the reference for that same state. The results represent this fictional-garage SUMO run, not a measured real facility or physical throughput. Waiting cost remains zero because the live allocator does not measure queue delay.",
                "",
                "### Optimizer graphs",
                "",
                "![Mean allocation cost by algorithm](optimization_results/figures/average_allocation_cost.png)",
                "![Optimizer runtime by algorithm](optimization_results/figures/execution_time.png)",
                "![Allocation cost by occupancy level](optimization_results/figures/cost_by_occupancy.png)",
                "![Optimality gap by algorithm](optimization_results/figures/optimality_gap_distribution.png)",
                "![Objective components by algorithm](optimization_results/figures/objective_components.png)",
            ]
        )
    else:
        lines.append("Optimizer benchmarks are unavailable; run `make review-optimizers`.")
    lines.extend(
        [
            "",
            "## Current dashboard and parking workflow",
            "",
            "The browser renders a fictional six-level garage and city connected to SUMO/TraCI. The garage contains 2,376 modeled bays across six 396-bay decks: two below ground and four above ground, joined by ramps. Published Haneda P2 floor guides inform the geometry; the basement and city are emulations, not an exact map of Phoenix Marketcity or Haneda. Roads, buildings, landscaping, trees, pedestrians, street lights, signals, moving traffic, gates, and ramps are part of the animated scene. The five RFID-equipped spaces remain the physical prototype; every modeled bay has a software occupancy record.",
            "",
            "SUMO controls include start, stop, pause, resume, and reset, with live simulated time, vehicle count, mean speed, and parking event updates. Each SUMO vehicle ID maps to a stable pseudonymous parking identity across simulation runs, with run-specific idempotency keys for entry, exit, and rollback. Road vehicles arriving at the garage enter a session, leave the road flow while parked, then exit the session and rejoin traffic after an emulated dwell. Admission is limited to two vehicles per simulation step. This is controlled software traffic, not measured facility throughput.",
            "",
            "Vehicle entry supports a connected RFID reader or manual ID simulation through the same API. UIDs are normalized into unique vehicle identities, with at most one active session per identity and separate records for repeat visits. Entry follows a first-person route to the assigned floor/bay and marks the destination on a parking map; exit releases the bay and animates departure. The dashboard displays a QR-linked receipt with identity, bay, timestamps, duration, tariff, and amount. It provides a live estimate while parked and a final charge at exit; it does not accept payment or settle a transaction.",
            "",
            "The demo tariff is ₹50 for the first started hour, ₹40 per additional started hour, the first 10 minutes free, and ₹400 maximum per 24 hours. It is an illustrative rule, not a verified mall tariff. RFID identity keeps vehicle/session history distinct but does not change the tariff. Live allocation includes personalized fairness: each candidate bay is scored by the absolute difference between that vehicle's projected mean walking distance after assignment and the equal-weighted mean of each other vehicle's historical mean walking distance across completed sessions. Stable SUMO identities preserve this history across simulation runs. The score uses configured bay distances, is neutral at zero when there is no peer history, and is capped from 0 to 1. Waiting remains zero because the model does not measure queue wait. This is an allocation proxy, not a guarantee of equitable outcomes. The optimizer benchmark uses allocation states captured from the executed SUMO/TraCI run; its conclusions apply to this modeled traffic run, not a field-measured parking facility.",
            "",
            "The 3D captures below document the modeled city, garage, and navigation views. They are interface evidence, not measured traffic outcomes.",
            "",
            "![Fictional city district](final_submission/figures/city_district_overview.png)",
            "![Six-level garage with basement decks and ramps](final_submission/figures/six_floor_garage.png)",
            "![First-person vehicle route to the assigned bay](final_submission/figures/first_person_route.png)",
            "![Parking map with route and destination](final_submission/figures/parking_navigation_map.png)",
            "",
            "## Hardware status and engineering estimates",
            "",
            "The latest post-rewire tabletop validation record captures two RFID reads and two successful entry/exit API transactions (2/2 HTTP 200). It also records the S1 occupancy transition. Physical LED visibility, OLED behavior, servo motion, and current draw were not independently verified. Two earlier RC522 SPI probes returned 0xFF and 0x00 before rewire; they do not describe the latest successful reads. Two trials are insufficient to infer a reliability rate.",
            "",
            "The following are rough engineering planning estimates, not hardware measurements or simulated benchmark results. Success-rate and latency ranges are low-confidence analyst assumptions for close-range tabletop use on a stable local Wi-Fi network. Replace them with trial data before making performance claims. Component values use the firmware and manufacturer specifications where available.",
            "",
            "| Quantity | Rough estimate | Basis and limitation |",
            "| --- | ---: | --- |",
            "| RFID successful reads per close, aligned tap | 90-99% (very low confidence) | Assumes a supported tag within about 20 mm, stable 3.3 V, and no nearby metal. MFRC522 specifies up to 50 mm depending on antenna tuning; this is not a success-rate guarantee ([NXP datasheet](https://www.nxp.com/docs/en/data-sheet/MFRC522.pdf)). |",
            "| API entry/exit transaction success on stable LAN | 98-99.5% (very low confidence) | Planning assumption for healthy Wi-Fi and backend; no post-rewire trial series was captured. |",
            "| LED correctness with known slot state | 95-100% (very low confidence) | Assumes correct wiring/polarity and status refresh; no expected-versus-observed trials. |",
            "| Entry/exit latency, tag detection to accepted response | 0.2-1.0 s (low confidence) | Order-of-magnitude estimate for one local request and SQLite transaction. Firmware's 3.5 s HTTP timeout is a failure limit, not expected latency. |",
            "| Wi-Fi recovery after AP is available | 5-15 s (low confidence) | Firmware retries every 5 s; range allows up to 10 s association/DHCP after retry. |",
            "| Servo command delay after RFID detection | 0.2-1.0 s (low confidence) | Assumes one healthy local API round trip; excludes mechanical travel. |",
            "| SG90 10°→85° travel | 0.13-0.50 s (very low confidence) | Nominal ideal is 125 ms from 75° x 0.1 s/60° at 4.8 V; upper range adds load/settling allowance ([TowerPro](https://towerpro.com.tw/product/sg90-7/)). |",
            "| Controller free heap | Measured historical mean 274,069 bytes (n=8) | Captured serial telemetry during earlier controller runs; median 292,240, SD 26,019, p95 293,416 bytes. This is measured, not an estimate. |",
            "| Controller + reader + OLED + LEDs input current, servo excluded | 0.15-0.40 A at 5 V (very low confidence) | Budget estimate from ESP32 active Wi-Fi current plus peripheral allowance; regulator and duty cycle vary ([Espressif datasheet](https://documentation.espressif.com/esp32_datasheet_en.html)). |",
            "| SG90 servo supply current | 0.5-2.0 A (very low confidence) | Manufacturer product page notes this range; exact servo/load is unknown. Use separate regulated supply ([TowerPro](https://towerpro.com.tw/product/sg90-7/)). |",
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
