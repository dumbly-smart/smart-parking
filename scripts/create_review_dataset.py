"""Generate the isolated synthetic review database and privacy-safe exports."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import zipfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from backend.app.config import Settings
from backend.app.db import Database
from prediction.data import build_feature_timeline, prepare_prediction_dataset
from prediction.demo_data import DemoDataConfig, replace_prediction_demo_data
from prediction.models import FEATURE_NAMES, TARGET_NAME

DEFAULT_ROOT = Path("review_outputs/2026-10-15")
DATASET_KEY = "academic-review-20261015"
SEED = 20260908
START_AT = datetime(2026, 8, 1, tzinfo=UTC)
DAYS = 14


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _raw_rows(database: Database) -> list[dict[str, object]]:
    """Read simulated source facts while excluding direct identifiers."""
    rows: list[dict[str, object]] = []
    with database.connect() as connection:
        contexts = connection.execute(
            """SELECT occupancy_count, weather, holiday, event, sampled_at
               FROM context_samples ORDER BY sampled_at"""
        ).fetchall()
        for row in contexts:
            rows.append(
                {
                    "record_type": "context",
                    "timestamp_utc": row["sampled_at"],
                    "occupancy_count": row["occupancy_count"],
                    "weather": row["weather"],
                    "holiday": row["holiday"],
                    "event": row["event"],
                }
            )
        sessions = connection.execute(
            """SELECT slot_id, entered_at, exited_at FROM parking_sessions
               ORDER BY entered_at, id"""
        ).fetchall()
        for row in sessions:
            rows.append(
                {
                    "record_type": "session",
                    "timestamp_utc": row["entered_at"],
                    "slot_id": row["slot_id"],
                    "entered_at_utc": row["entered_at"],
                    "exited_at_utc": row["exited_at"],
                }
            )
        allocations = connection.execute(
            """SELECT a.slot_id, a.created_at, r.best_cost, r.objective_breakdown
               FROM allocations a JOIN optimizer_runs r ON r.id=a.optimizer_run_id
               ORDER BY a.created_at, a.id"""
        ).fetchall()
        for row in allocations:
            components = json.loads(row["objective_breakdown"])
            rows.append(
                {
                    "record_type": "allocation",
                    "timestamp_utc": row["created_at"],
                    "slot_id": row["slot_id"],
                    "objective_cost": row["best_cost"],
                    "distance": components.get("distance"),
                    "congestion": components.get("congestion"),
                    "waiting": components.get("waiting"),
                    "fairness": components.get("fairness"),
                }
            )
    return sorted(rows, key=lambda row: (str(row["timestamp_utc"]), str(row["record_type"])))


def export_dataset(database: Database, output: Path) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    source = database.load_prediction_source_data()
    prepared = prepare_prediction_dataset(source)
    timeline = build_feature_timeline(source, prepared.config)
    if len(timeline) != DAYS * 24 * 60 // prepared.config.interval_minutes:
        raise ValueError("review dataset does not contain the expected complete timeline")

    raw_path = output / "parking_raw.csv"
    raw_fields = (
        "record_type",
        "timestamp_utc",
        "occupancy_count",
        "weather",
        "holiday",
        "event",
        "slot_id",
        "entered_at_utc",
        "exited_at_utc",
        "objective_cost",
        "distance",
        "congestion",
        "waiting",
        "fairness",
    )
    with raw_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=raw_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(_raw_rows(database))

    feature_path = output / "parking_features.csv"
    feature_fields = ("timestamp_utc", *FEATURE_NAMES, TARGET_NAME)
    with feature_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=feature_fields)
        writer.writeheader()
        for index, bucket in enumerate(timeline):
            if bucket is None:
                raise ValueError(f"feature timeline has a missing bucket at index {index}")
            following = timeline[index + 1] if index + 1 < len(timeline) else None
            row = {name: value for name, value in zip(FEATURE_NAMES, bucket.values, strict=True)}
            row.update(
                timestamp_utc=bucket.timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                **{TARGET_NAME: following.values[0] if following is not None else ""},
            )
            writer.writerow(row)

    raw_count = sum(1 for _ in raw_path.open(encoding="utf-8")) - 1
    feature_rows = len(timeline)
    metadata: dict[str, object] = {
        "dataset_type": "synthetic simulated parking-system observations",
        "origin": "prediction.demo_data deterministic generator; no real-world measurements",
        "dataset_key": DATASET_KEY,
        "random_seed": SEED,
        "slot_count": source.slot_count,
        "records": {"raw_observations": raw_count, "feature_timeline": feature_rows},
        "feature_count": len(FEATURE_NAMES),
        "feature_names": list(FEATURE_NAMES),
        "feature_definitions": {
            "occupancy_ratio": "occupied slots divided by configured capacity",
            "occupancy_change": "current occupancy ratio minus previous interval ratio",
            "occupancy_mean_15m": "mean occupancy ratio over the last three intervals",
            "occupancy_mean_60m": "mean occupancy ratio over the last twelve intervals",
            "hour_sin/hour_cos": "cyclic local-clock position; timestamps are UTC",
            "weekday_sin/weekday_cos": "cyclic day-of-week position",
            "weather_*": "one-hot weather category indicators",
            "holiday/event": "simulated binary calendar/event indicators",
            "entry_count/exit_count": "session starts/ends in the five-minute interval",
            "allocation_count": "allocations recorded in the interval",
            "active_session_count": "sessions active at interval end",
            "unique_vehicle_count": "distinct simulated vehicles represented by sessions in the interval",  # noqa: E501
            "returning_vehicle_rate": "share of interval entries by previously observed vehicles",
            "mean_walking_distance/mean_congestion/mean_fairness": "mean normalized allocation component, or zero without allocations",  # noqa: E501
            "allocation_present": "one when at least one allocation exists in the interval",
            TARGET_NAME: "occupancy ratio in the next five-minute interval; last row has no future target",  # noqa: E501
        },
        "target": TARGET_NAME,
        "sampling_interval_minutes": prepared.config.interval_minutes,
        "lookback_intervals": prepared.config.lookback_steps,
        "horizon_intervals": prepared.config.horizon_steps,
        "time_coverage_utc": {
            "start": prepared.source_started_at.isoformat().replace("+00:00", "Z"),
            "end": prepared.source_ended_at.isoformat().replace("+00:00", "Z"),
        },
        "preprocessing": {
            "missing_values": "short gaps carried forward by existing feature builder; longer gaps remain missing and are excluded from examples",  # noqa: E501
            "continuous_features": "standardized using training partition statistics only",
            "bounded_features": "kept on the existing [0, 1] contract",
            "split": "chronological 70% train / 15% validation / 15% test before window construction",  # noqa: E501
            "split_id": prepared.split_id,
            "sequence_counts": {
                "train": int(prepared.train.inputs.shape[0]),
                "validation": int(prepared.validation.inputs.shape[0]),
                "test": int(prepared.test.inputs.shape[0]),
            },
            "scaler": {
                "feature_names": [
                    FEATURE_NAMES[index] for index in prepared.scaler.feature_indices
                ],
                "means": list(prepared.scaler.means),
                "scales": list(prepared.scaler.scales),
            },
        },
        "privacy": "No RFID UID, vehicle ID, session ID, idempotency key, or secret is exported.",
        "limitations": "All values are simulated. The generator models five configured slots and does not represent measured site demand, actual weather, camera accuracy, or physical throughput.",  # noqa: E501
        "reproduction": "Run `make review-dataset` from the repository root.",
        "sha256": {
            "parking_raw.csv": _sha256(raw_path),
            "parking_features.csv": _sha256(feature_path),
        },
    }
    metadata_path = output / "dataset_metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    readme_path = output / "DATASET_README.md"
    definitions = "\n".join(
        f"- `{name}`: {description}"
        for name, description in metadata["feature_definitions"].items()
    )
    readme_path.write_text(
        "# Simulated parking review dataset\n\n"
        "## Origin and scope\n\n"
        "This is a deterministic synthetic dataset generated by the existing SQLite demo-data generator and prediction feature builder. No real-world measurements are included. The review database contains five configured slots and is isolated from the application database.\n\n"  # noqa: E501
        f"- Generator seed: `{SEED}`\n"
        f"- Sampling interval: {prepared.config.interval_minutes} minutes\n"
        f"- Time coverage (UTC): {metadata['time_coverage_utc']['start']} through {metadata['time_coverage_utc']['end']}\n"  # noqa: E501
        f"- Feature buckets: {feature_rows:,}; raw records: {raw_count:,}\n"
        f"- Model features: {len(FEATURE_NAMES)}; target: `{TARGET_NAME}`\n\n"
        "## Files\n\n"
        "- `parking_raw.csv`: privacy-safe context samples, session entry/exit records, and allocation objective components. Direct vehicle, session, RFID, and idempotency identifiers are excluded.\n"  # noqa: E501
        "- `parking_features.csv`: chronological features from the existing shared `build_feature_timeline` implementation, plus the next-interval occupancy target. The last row has no future target and is blank.\n"  # noqa: E501
        "- `dataset_metadata.json`: machine-readable schema, split, scaler, limitations, and SHA-256 details.\n"  # noqa: E501
        "- `parking_dataset.zip`: this README, metadata, and both CSV files.\n\n"
        "## Feature definitions\n\n"
        f"{definitions}\n\n"
        "## Prediction and preprocessing\n\n"
        f"The target `{TARGET_NAME}` is occupancy ratio five minutes after each feature timestamp. Each example uses the preceding twelve intervals (60 minutes). The chronological split is 70% train, 15% validation, and 15% test before window construction; actual sequence counts are train {prepared.train.inputs.shape[0]:,}, validation {prepared.validation.inputs.shape[0]:,}, and test {prepared.test.inputs.shape[0]:,}.\n\n"  # noqa: E501
        "Continuous features are standardized using training-partition values only. Bounded and cyclic encodings follow the shared preprocessing contract. The feature builder carries short gaps forward and leaves longer gaps unresolved; sequence construction excludes windows spanning unresolved buckets. This export has no unresolved buckets. RFID values never enter model arrays.\n\n"  # noqa: E501
        "## Limitations\n\n"
        "All observations are simulated. The generator does not model a measured site, actual weather, camera accuracy, physical throughput, or real waiting times. Five-slot results may not generalize to other facilities.\n\n"  # noqa: E501
        "## Reproduction and checksums\n\n"
        "From the repository root, run `make review-dataset`. The command recreates the dedicated review database and all exports using the seed and interval listed above. SHA-256 checksums for the raw and feature CSV files are recorded in `dataset_metadata.json`.\n",  # noqa: E501
        encoding="utf-8",
    )
    zip_path = output / "parking_dataset.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in (raw_path, feature_path, metadata_path, readme_path):
            archive.write(path, arcname=path.name)
    return metadata


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_ROOT / "dataset")
    parser.add_argument(
        "--database-url",
        default=f"sqlite:///{(DEFAULT_ROOT / 'dataset' / 'review.db').as_posix()}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        settings = Settings(database_url=args.database_url)
        database = Database(settings.database_path)
        database.initialize(settings.parking.slots)
        replace_prediction_demo_data(
            database,
            DemoDataConfig(dataset_key=DATASET_KEY, seed=SEED, start_at=START_AT, days=DAYS),
        )
        metadata = export_dataset(database, args.output_dir)
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(metadata, sort_keys=True))
    print(f"dataset_zip={args.output_dir / 'parking_dataset.zip'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
