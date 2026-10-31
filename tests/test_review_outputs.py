from __future__ import annotations

import csv
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

from backend.app.config import Settings
from backend.app.db import Database
from optimization.models import AllocationRequest, SlotCandidate
from prediction.demo_data import DemoDataConfig, replace_prediction_demo_data
from scripts.create_review_dataset import DATASET_KEY, DAYS, SEED, START_AT, export_dataset
from scripts.generate_experimental_report import generate as generate_experimental_report
from scripts.package_prediction_artifacts import package
from scripts.run_optimizer_benchmarks import ObservedScenario, run_experiments


def test_review_export_is_loadable_privacy_safe_and_checksummed(tmp_path) -> None:
    database = Database(tmp_path / "review.db")
    settings = Settings()
    database.initialize(settings.parking.slots)
    replace_prediction_demo_data(
        database,
        DemoDataConfig(dataset_key=DATASET_KEY, seed=SEED, start_at=START_AT, days=DAYS),
    )

    output = tmp_path / "dataset"
    metadata = export_dataset(database, output)

    with (output / "parking_features.csv").open(newline="", encoding="utf-8") as stream:
        features = list(csv.DictReader(stream))
    with (output / "parking_raw.csv").open(newline="", encoding="utf-8") as stream:
        raw = list(csv.DictReader(stream))
    assert len(features) == DAYS * 24 * 12
    assert len(raw) == metadata["records"]["raw_observations"]
    assert features[0]["timestamp_utc"] < features[-1]["timestamp_utc"]
    assert features[-1]["next_occupancy_ratio"] == ""
    assert "rfid" not in ",".join(raw[0]).lower()
    assert "vehicle_id" not in ",".join(raw[0]).lower()
    raw_text = (output / "parking_raw.csv").read_text(encoding="utf-8")
    assert "demo-rfid" not in raw_text
    for filename, digest in metadata["sha256"].items():
        assert hashlib.sha256((output / filename).read_bytes()).hexdigest() == digest
    with zipfile.ZipFile(output / "parking_dataset.zip") as archive:
        assert set(archive.namelist()) == {
            "parking_raw.csv",
            "parking_features.csv",
            "dataset_metadata.json",
            "DATASET_README.md",
        }
        assert json.loads(archive.read("dataset_metadata.json"))["feature_count"] == 27


def test_optimizer_benchmark_uses_observed_sumo_allocation_requests(tmp_path) -> None:
    weights = Settings().parking.allocation.weights
    request = AllocationRequest(
        scenario_id="entry:sumo-observed-001",
        candidates=(
            SlotCandidate(
                slot_id=1,
                occupied=True,
                distance=0.17,
                congestion=0.25,
                waiting=0.0,
                fairness=0.11,
            ),
            SlotCandidate(
                slot_id=2,
                occupied=False,
                distance=0.42,
                congestion=0.25,
                waiting=0.0,
                fairness=0.05,
            ),
            SlotCandidate(
                slot_id=3,
                occupied=False,
                distance=0.81,
                congestion=0.0,
                waiting=0.0,
                fairness=0.22,
            ),
        ),
        weights=weights,
        seed=9876,
    )
    observed = ObservedScenario(
        request=request,
        simulation_time=124.5,
        traffic_vehicle_count=7,
        parked_vehicle_count=2,
    )

    summary = run_experiments(tmp_path, [observed], repeats=2)

    assert summary["source"] == "executed_sumo_parking_allocations"
    assert summary["scenario_count"] == 1
    assert summary["candidate_capacity"] == 3
    with (tmp_path / "benchmark_runs.csv").open(newline="", encoding="utf-8") as stream:
        runs = list(csv.DictReader(stream))
    assert len(runs) == 12
    assert {row["scenario_id"] for row in runs} == {request.scenario_id}
    assert {row["observed_simulation_time"] for row in runs} == {"124.5"}
    with (tmp_path / "sumo_observed_scenarios.jsonl").open(encoding="utf-8") as stream:
        evidence = json.loads(next(stream))
    assert evidence["traffic_vehicle_count"] == 7
    assert evidence["parked_vehicle_count"] == 2
    assert [candidate["distance"] for candidate in evidence["candidates"]] == [
        0.17,
        0.42,
        0.81,
    ]


def test_experimental_report_lists_all_optimizer_results(tmp_path) -> None:
    source = Path(__file__).resolve().parents[1] / "review_outputs/2026-10-15/optimization_results"
    output = tmp_path / "optimization_results"
    output.mkdir()
    for name in ("optimizer_summary.json", "optimizer_comparison.csv"):
        shutil.copy2(source / name, output / name)

    generate_experimental_report(tmp_path)

    report = (tmp_path / "EXPERIMENTAL_REPORT.md").read_text(encoding="utf-8")
    for algorithm in ("NSGA-II", "GA", "PSO", "ACO", "first_available", "exhaustive_optimum"):
        assert f"| {algorithm} |" in report
    for feature in (
        (
            "Forecasting observations are synthetic; optimizer scenarios "
            "come from parking allocations captured"
        ),
        "SUMO-observed",
        "Candidate snapshots and their objective values are preserved",
        "Configuration, network, and route SHA-256 hashes are recorded",
        "2,376 modeled bays",
        "SUMO controls include start, stop, pause, resume, and reset",
        "first-person route",
        "QR-linked receipt",
        "stable pseudonymous parking identity across simulation runs",
        "Live allocation includes personalized fairness",
        "equal-weighted mean of each other vehicle's historical mean walking distance",
        "SUMO-observed",
    ):
        assert feature in report
    assert "objective values are synthetic" not in report.lower()
    for figure in (
        "average_allocation_cost.png",
        "execution_time.png",
        "cost_by_occupancy.png",
        "optimality_gap_distribution.png",
        "objective_components.png",
    ):
        assert f"optimization_results/figures/{figure}" in report


def test_model_package_contains_only_hash_verified_models_and_manifests(tmp_path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    split_id = "a" * 64
    for model in ("lstm", "gru", "transformer"):
        model_bytes = f"real-{model}-payload".encode()
        digest = hashlib.sha256(model_bytes).hexdigest()
        filename = f"{model}.keras"
        (artifacts / filename).write_bytes(model_bytes)
        (artifacts / f"{model}-run.json").write_text(
            json.dumps(
                {
                    "model": model,
                    "artifact_filename": filename,
                    "artifact_sha256": digest,
                    "split_id": split_id,
                }
            ),
            encoding="utf-8",
        )

    output = package(artifacts, tmp_path / "models.zip")
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        index = json.loads(archive.read("artifact_index.json"))
        assert {entry["model"] for entry in index} == {"lstm", "gru", "transformer"}
        assert all(
            f"manifests/{model}-run.json" in archive.namelist()
            for model in ("lstm", "gru", "transformer")
        )
