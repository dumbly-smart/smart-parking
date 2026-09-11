"""Safe, bucket-aligned runtime occupancy forecasting."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import numpy as np

from backend.app.db import Database
from prediction.artifacts import load_manifest
from prediction.data import build_runtime_input, prepare_prediction_dataset
from prediction.models import PredictionDataError
from prediction.training import ModelFamily, PredictionTrainingError

PredictorName = Literal["baseline", "lstm", "gru", "transformer"]


@dataclass(frozen=True)
class PredictionForecast:
    model: PredictorName
    occupancy_ratio: float
    target_at: datetime
    fallback_reason: str | None = None


class PredictionService:
    def __init__(
        self,
        database: Database,
        selected_predictor: PredictorName,
        artifact_directory: Path,
        *,
        _model_loader: Callable[[Path], Any] | None = None,
    ) -> None:
        self._database = database
        self._selected_predictor = selected_predictor
        self._artifact_directory = Path(artifact_directory)
        self._model_loader = _model_loader or self._load_model
        self._cache: dict[datetime, PredictionForecast] = {}

    @staticmethod
    def _load_model(path: Path) -> Any:
        try:
            from prediction.architectures import _require_tensorflow

            tensorflow = _require_tensorflow()
            return tensorflow.keras.models.load_model(path)
        except PredictionTrainingError:
            raise
        except Exception as error:
            raise PredictionTrainingError("invalid_manifest", "model cannot be loaded") from error

    @staticmethod
    def _fallback_target() -> datetime:
        current = datetime.now(UTC).replace(second=0, microsecond=0)
        return current + timedelta(minutes=5 - current.minute % 5)

    def forecast(self) -> PredictionForecast:
        try:
            source = self._database.load_prediction_source_data()
            dataset = prepare_prediction_dataset(source)
            runtime = build_runtime_input(source, dataset)
        except PredictionDataError:
            return PredictionForecast(
                model="baseline",
                occupancy_ratio=0.0,
                target_at=self._fallback_target(),
                fallback_reason="insufficient_history",
            )
        cached = self._cache.get(runtime.target_at)
        if cached is not None:
            return cached
        baseline = PredictionForecast(
            model="baseline",
            occupancy_ratio=runtime.latest_occupancy_ratio,
            target_at=runtime.target_at,
        )
        if self._selected_predictor == "baseline":
            self._cache[runtime.target_at] = baseline
            return baseline
        try:
            selected = ModelFamily(self._selected_predictor)
            run = next(
                item
                for item in self._database.list_prediction_results()
                if item.model is selected
            )
            filename = run.artifact_metadata.get("manifest_filename")
            if (
                not isinstance(filename, str)
                or Path(filename).name != filename
                or not filename.endswith(".json")
            ):
                raise PredictionTrainingError("invalid_manifest", "manifest filename is invalid")
            manifest = load_manifest(
                self._artifact_directory / filename,
                expected_dataset=dataset,
            )
            if not manifest.runtime_compatible:
                return self._cache_fallback(runtime.target_at, baseline, "no_compatible_artifact")
            model = self._model_loader(self._artifact_directory / manifest.artifact_filename)
            output = np.asarray(model.predict(runtime.inputs, verbose=0), dtype=np.float64)
            if output.shape not in ((1,), (1, 1)):
                raise PredictionTrainingError(
                    "invalid_prediction", "model output has invalid shape"
                )
            prediction = float(output.reshape(-1)[0])
            if not math.isfinite(prediction) or not 0 <= prediction <= 1:
                raise PredictionTrainingError(
                    "invalid_prediction", "model output is outside [0, 1]"
                )
        except StopIteration:
            return self._cache_fallback(runtime.target_at, baseline, "no_compatible_artifact")
        except PredictionTrainingError as error:
            reason = (
                "missing_ml_dependency"
                if error.code == "missing_ml_dependency"
                else "invalid_prediction"
                if error.code == "invalid_prediction"
                else "invalid_artifact"
            )
            return self._cache_fallback(runtime.target_at, baseline, reason)
        result = PredictionForecast(
            model=selected.value,
            occupancy_ratio=prediction,
            target_at=runtime.target_at,
        )
        self._cache[runtime.target_at] = result
        return result

    def _cache_fallback(
        self, target_at: datetime, baseline: PredictionForecast, reason: str
    ) -> PredictionForecast:
        result = PredictionForecast(
            model="baseline",
            occupancy_ratio=baseline.occupancy_ratio,
            target_at=target_at,
            fallback_reason=reason,
        )
        self._cache[target_at] = result
        return result
