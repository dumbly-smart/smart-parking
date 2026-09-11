"""Seed deterministic, safely replaceable history for prediction development."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, datetime

from backend.app.config import Settings
from backend.app.db import Database
from prediction.demo_data import DemoDataConfig, replace_prediction_demo_data


def _parse_start_at(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise argparse.ArgumentTypeError("start time must be ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise argparse.ArgumentTypeError("start time must be timezone-aware UTC")
    return parsed.astimezone(UTC)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url")
    parser.add_argument("--dataset-key", default="prediction-demo")
    parser.add_argument("--seed", type=int, default=20260908)
    parser.add_argument(
        "--start-at", type=_parse_start_at, default=datetime(2026, 8, 1, tzinfo=UTC)
    )
    parser.add_argument("--days", type=int, default=14)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    setting_values = {}
    if args.database_url is not None:
        setting_values["database_url"] = args.database_url
    settings = Settings(**setting_values)
    database = Database(settings.database_path)
    database.initialize(settings.parking.slots)
    summary = replace_prediction_demo_data(
        database,
        DemoDataConfig(
            dataset_key=args.dataset_key,
            seed=args.seed,
            start_at=args.start_at,
            days=args.days,
        ),
    )
    print(json.dumps(summary.as_dict(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
