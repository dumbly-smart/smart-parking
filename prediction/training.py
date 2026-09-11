"""Shared contracts for prediction model training and comparison."""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from numbers import Real
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from prediction.models import FEATURE_NAMES, TARGET_NAME, PreparedDataset, PreparedSplit


class PredictionTrainingError(ValueError):
    """Training failure with a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class ModelFamily(StrEnum):
    LSTM = "lstm"
    GRU = "gru"
    TRANSFORMER = "transformer"


@dataclass(frozen=True)
class TrainingConfig:
    model: ModelFamily = ModelFamily.GRU
    seed: int = 20260908
    epochs: int = 12
    batch_size: int = 32
    learning_rate: float = 0.001
    patience: int = 3
    recurrent_units: int = 16
    transformer_width: int = 16
    transformer_heads: int = 2
    latency_repetitions: int = 5

    def __post_init__(self) -> None:
        try:
            model = ModelFamily(self.model)
        except (TypeError, ValueError) as error:
            raise PredictionTrainingError(
                "unsupported_model", "model must be lstm, gru, or transformer"
            ) from error
        object.__setattr__(self, "model", model)

        positive_integers = (
            "epochs",
            "batch_size",
            "recurrent_units",
            "transformer_width",
            "transformer_heads",
            "latency_repetitions",
        )
        for name in ("seed", "patience", *positive_integers):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise PredictionTrainingError(
                    "invalid_training_config", f"{name} must be an integer"
                )
        for name in positive_integers:
            if getattr(self, name) <= 0:
                raise PredictionTrainingError(
                    "invalid_training_config", f"{name} must be positive"
                )
        if self.patience < 0:
            raise PredictionTrainingError(
                "invalid_training_config", "patience must be non-negative"
            )
        if (
            not isinstance(self.learning_rate, Real)
            or isinstance(self.learning_rate, bool)
            or not math.isfinite(self.learning_rate)
            or self.learning_rate <= 0
        ):
            raise PredictionTrainingError(
                "invalid_training_config", "learning_rate must be finite and positive"
            )
        if self.transformer_width % self.transformer_heads:
            raise PredictionTrainingError(
                "invalid_training_config",
                "transformer_width must be divisible by transformer_heads",
            )


@dataclass(frozen=True)
class EvaluationMetrics:
    mae: float
    mse: float
    rmse: float
    inference_latency_ms: float = 0.0


@dataclass(frozen=True)
class TrainingResult:
    model: ModelFamily
    split_id: str
    metrics: EvaluationMetrics
    manifest_path: Path


class _TrainingBackend(Protocol):
    def build(self, config: TrainingConfig, dataset: PreparedDataset) -> Any: ...

    def fit(
        self,
        model: Any,
        train: PreparedSplit,
        validation: PreparedSplit,
        config: TrainingConfig,
    ) -> None: ...

    def predict(self, model: Any, inputs: np.ndarray) -> np.ndarray: ...

    def framework_versions(self) -> dict[str, str]: ...


class _TensorFlowBackend:
    def build(self, config: TrainingConfig, dataset: PreparedDataset) -> Any:
        from prediction.architectures import build_model

        return build_model(config, dataset.train.inputs.shape[1:])

    def fit(
        self,
        model: Any,
        train: PreparedSplit,
        validation: PreparedSplit,
        config: TrainingConfig,
    ) -> None:
        from prediction.architectures import _require_tensorflow

        tf = _require_tensorflow()
        early_stopping = tf.keras.callbacks.EarlyStopping(
            monitor="val_loss",
            patience=config.patience,
            restore_best_weights=True,
        )
        model.fit(
            train.inputs,
            train.targets,
            validation_data=(validation.inputs, validation.targets),
            epochs=config.epochs,
            batch_size=config.batch_size,
            shuffle=False,
            callbacks=[early_stopping],
            verbose=0,
        )

    def predict(self, model: Any, inputs: np.ndarray) -> np.ndarray:
        return np.asarray(model.predict(inputs, verbose=0))

    def framework_versions(self) -> dict[str, str]:
        from prediction.architectures import _require_tensorflow

        tf = _require_tensorflow()
        return {
            "tensorflow": str(tf.__version__),
            "keras": str(getattr(tf.keras, "__version__", "bundled")),
        }


def _validate_dataset(dataset: PreparedDataset) -> None:
    if not isinstance(dataset, PreparedDataset):
        raise PredictionTrainingError(
            "incompatible_dataset", "training requires one PreparedDataset"
        )
    expected_shape = (dataset.config.lookback_steps, len(FEATURE_NAMES))
    if (
        dataset.feature_names != FEATURE_NAMES
        or dataset.target_name != TARGET_NAME
        or dataset.config.interval_minutes != 5
        or dataset.config.lookback_steps != 12
        or dataset.config.horizon_steps != 1
        or any(
            split.inputs.shape[1:] != expected_shape
            for split in (dataset.train, dataset.validation, dataset.test)
        )
    ):
        raise PredictionTrainingError(
            "incompatible_dataset", "prepared dataset does not match the forecast contract"
        )


def default_comparison_configs() -> tuple[TrainingConfig, ...]:
    """Return equal-capacity defaults in the fixed comparison order."""
    return tuple(TrainingConfig(model=model) for model in ModelFamily)


def train_model(
    dataset: PreparedDataset,
    config: TrainingConfig,
    artifact_directory: Path,
    *,
    _backend: _TrainingBackend | None = None,
) -> TrainingResult:
    """Train and evaluate one family using only the prepared dataset boundary."""
    from prediction.artifacts import publish_artifact
    from prediction.evaluation import evaluate_predictions, measure_inference_latency

    _validate_dataset(dataset)
    if not isinstance(config, TrainingConfig):
        raise PredictionTrainingError(
            "invalid_training_config", "config must be a TrainingConfig"
        )
    backend = _backend if _backend is not None else _TensorFlowBackend()
    try:
        model = backend.build(config, dataset)
        backend.fit(model, dataset.train, dataset.validation, config)
        predictions = backend.predict(model, dataset.test.inputs)
        quality = evaluate_predictions(predictions, dataset.test.targets)
        latency = measure_inference_latency(
            lambda inputs: backend.predict(model, inputs),
            dataset.test.inputs,
            config.latency_repetitions,
        )
        metrics = EvaluationMetrics(
            mae=quality.mae,
            mse=quality.mse,
            rmse=quality.rmse,
            inference_latency_ms=latency,
        )
        versions = backend.framework_versions()
    except PredictionTrainingError:
        raise
    except Exception as error:
        raise PredictionTrainingError(
            "training_failed", f"{config.model.value} training failed"
        ) from error
    manifest_path = publish_artifact(
        model,
        dataset,
        config,
        metrics,
        Path(artifact_directory),
        framework_versions=versions,
    )
    return TrainingResult(config.model, dataset.split_id, metrics, manifest_path)


def compare_models(
    dataset: PreparedDataset,
    configs: Sequence[TrainingConfig],
    artifact_directory: Path,
    *,
    _backend: _TrainingBackend | None = None,
) -> tuple[TrainingResult, ...]:
    """Train all fixed model families against the exact same prepared dataset."""
    _validate_dataset(dataset)
    resolved = tuple(configs)
    if len(resolved) != len(ModelFamily) or any(
        not isinstance(config, TrainingConfig) for config in resolved
    ):
        raise PredictionTrainingError(
            "invalid_training_config", "comparison requires one config per model family"
        )
    by_model = {config.model: config for config in resolved}
    if set(by_model) != set(ModelFamily) or len(by_model) != len(resolved):
        raise PredictionTrainingError(
            "invalid_training_config", "comparison model configs must be unique and complete"
        )
    return tuple(
        train_model(
            dataset,
            by_model[model],
            artifact_directory,
            _backend=_backend,
        )
        for model in ModelFamily
    )
