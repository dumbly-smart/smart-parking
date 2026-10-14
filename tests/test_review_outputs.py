from __future__ import annotations

import csv
import hashlib
import json
import zipfile

from backend.app.config import Settings
from backend.app.db import Database
from prediction.demo_data import DemoDataConfig, replace_prediction_demo_data
from scripts.create_review_dataset import DATASET_KEY, DAYS, SEED, START_AT, export_dataset
from scripts.run_optimizer_benchmarks import _scenario


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


def test_optimizer_scenarios_are_seeded_and_share_normalized_candidates() -> None:
    weights = Settings().parking.allocation.weights
    first = _scenario(42, 9876, weights)
    repeat = _scenario(42, 9876, weights)
    assert first == repeat
    assert len(first.candidates) == 5
    assert len({candidate.slot_id for candidate in first.candidates}) == 5
    assert all(
        0 <= value <= 1
        for item in first.candidates
        for value in (
            item.distance,
            item.congestion,
            item.waiting,
            item.fairness,
        )
    )
