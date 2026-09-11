"""Train and compare all prediction model families from one prepared dataset."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from backend.app.config import Settings
from backend.app.db import Database
from prediction.data import prepare_prediction_dataset
from prediction.training import (
    PredictionTrainingError,
    compare_models,
    default_comparison_configs,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url")
    parser.add_argument("--artifact-directory", type=Path, required=True)
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


if __name__ == "__main__":
    raise SystemExit(main())
