"""Framework-independent prediction quality and latency evaluation."""

import math
import statistics
import time
from collections.abc import Callable

import numpy as np

from prediction.training import EvaluationMetrics, PredictionTrainingError


def _prediction_vector(values: np.ndarray, expected_count: int) -> np.ndarray:
    vector = np.array(values, dtype=np.float64, copy=True)
    if vector.ndim == 2 and vector.shape[1:] == (1,):
        vector = vector[:, 0]
    if vector.ndim != 1 or vector.shape[0] != expected_count:
        raise PredictionTrainingError(
            "invalid_prediction", "predictions must contain one scalar per test example"
        )
    if not np.isfinite(vector).all() or np.any((vector < 0) | (vector > 1)):
        raise PredictionTrainingError(
            "invalid_prediction", "predictions must be finite values in [0, 1]"
        )
    return vector


def evaluate_predictions(
    predictions: np.ndarray,
    targets: np.ndarray,
    *,
    inference_latency_ms: float = 0.0,
) -> EvaluationMetrics:
    """Evaluate one scalar occupancy-ratio prediction per target."""
    target_vector = np.array(targets, dtype=np.float64, copy=True)
    if target_vector.ndim != 1 or target_vector.size == 0:
        raise PredictionTrainingError(
            "incompatible_dataset", "test targets must be a non-empty vector"
        )
    if not np.isfinite(target_vector).all() or np.any(
        (target_vector < 0) | (target_vector > 1)
    ):
        raise PredictionTrainingError(
            "incompatible_dataset", "test targets must be finite values in [0, 1]"
        )
    vector = _prediction_vector(predictions, target_vector.shape[0])
    if not math.isfinite(inference_latency_ms) or inference_latency_ms < 0:
        raise PredictionTrainingError(
            "invalid_prediction", "inference latency must be finite and non-negative"
        )
    errors = vector - target_vector
    mse = float(np.mean(np.square(errors), dtype=np.float64))
    return EvaluationMetrics(
        mae=float(np.mean(np.abs(errors), dtype=np.float64)),
        mse=mse,
        rmse=math.sqrt(mse),
        inference_latency_ms=float(inference_latency_ms),
    )


def measure_inference_latency(
    predict: Callable[[np.ndarray], np.ndarray],
    inputs: np.ndarray,
    repetitions: int,
    *,
    _clock_ns: Callable[[], int] = time.perf_counter_ns,
) -> float:
    """Measure median warm-inference milliseconds per example."""
    if not isinstance(repetitions, int) or isinstance(repetitions, bool) or repetitions <= 0:
        raise PredictionTrainingError(
            "invalid_training_config", "latency repetitions must be a positive integer"
        )
    if not isinstance(inputs, np.ndarray) or inputs.ndim < 1 or inputs.shape[0] == 0:
        raise PredictionTrainingError(
            "incompatible_dataset", "latency inputs must contain at least one example"
        )
    predict(inputs)
    durations: list[int] = []
    for _ in range(repetitions):
        started = _clock_ns()
        predict(inputs)
        durations.append(_clock_ns() - started)
    median_ns = statistics.median(durations)
    return float(median_ns) / 1_000_000 / inputs.shape[0]
