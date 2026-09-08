"""Shared contracts for prediction model training and comparison."""

import math
from dataclasses import dataclass
from enum import StrEnum
from numbers import Real


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
