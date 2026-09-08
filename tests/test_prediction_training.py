import math

import numpy as np
import pytest

from prediction.evaluation import evaluate_predictions, measure_inference_latency
from prediction.training import PredictionTrainingError, TrainingConfig


@pytest.mark.parametrize(
    "overrides",
    [
        {"seed": True},
        {"epochs": 0},
        {"batch_size": 0},
        {"learning_rate": float("nan")},
        {"patience": -1},
        {"transformer_width": 15},
        {"latency_repetitions": 0},
    ],
)
def test_training_config_rejects_invalid_values(overrides: dict[str, object]) -> None:
    with pytest.raises(PredictionTrainingError) as raised:
        TrainingConfig(**overrides)

    assert raised.value.code == "invalid_training_config"


def test_evaluate_predictions_uses_hand_calculated_metrics() -> None:
    result = evaluate_predictions(
        np.array([0.0, 0.75], dtype=np.float64),
        np.array([0.25, 0.25], dtype=np.float64),
    )

    assert result.mae == pytest.approx(0.375)
    assert result.mse == pytest.approx(0.15625)
    assert result.rmse == pytest.approx(math.sqrt(0.15625))
    assert result.inference_latency_ms == 0.0


def test_evaluate_predictions_accepts_keras_scalar_shape() -> None:
    result = evaluate_predictions(
        np.array([[0.25], [0.5]], dtype=np.float32),
        np.array([0.25, 0.5], dtype=np.float64),
    )

    assert result.mae == 0.0


@pytest.mark.parametrize(
    "predictions",
    [
        np.array([0.2]),
        np.array([[0.2, 0.3], [0.4, 0.5]]),
        np.array([np.nan, 0.2]),
        np.array([-0.1, 0.2]),
        np.array([0.2, 1.1]),
    ],
)
def test_evaluate_predictions_rejects_invalid_outputs(predictions: np.ndarray) -> None:
    with pytest.raises(PredictionTrainingError) as raised:
        evaluate_predictions(predictions, np.array([0.2, 0.2]))

    assert raised.value.code == "invalid_prediction"


def test_measure_latency_excludes_warmup_and_reports_median_per_example() -> None:
    calls: list[np.ndarray] = []
    clock_values = iter([0, 4_000_000, 10_000_000, 16_000_000, 20_000_000, 30_000_000])

    def predict(inputs: np.ndarray) -> np.ndarray:
        calls.append(inputs)
        return np.zeros((len(inputs), 1))

    inputs = np.zeros((2, 12, 3))
    latency = measure_inference_latency(
        predict,
        inputs,
        repetitions=3,
        _clock_ns=lambda: next(clock_values),
    )

    assert len(calls) == 4
    assert latency == pytest.approx(3.0)
