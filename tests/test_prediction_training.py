import hashlib
import json
import math
from dataclasses import replace
from datetime import UTC, datetime
from importlib.util import find_spec
from pathlib import Path

import numpy as np
import pytest

import prediction.architectures as architectures
from prediction.artifacts import load_manifest, publish_artifact
from prediction.evaluation import evaluate_predictions, measure_inference_latency
from prediction.models import (
    CONTINUOUS_FEATURE_NAMES,
    FEATURE_NAMES,
    TARGET_NAME,
    PreparedDataset,
    PreparedSplit,
    PreprocessingConfig,
    ScalerMetadata,
)
from prediction.training import (
    EvaluationMetrics,
    ModelFamily,
    PredictionTrainingError,
    TrainingConfig,
    compare_models,
    default_comparison_configs,
    train_model,
)


def prepared_dataset() -> PreparedDataset:
    config = PreprocessingConfig()
    width = len(FEATURE_NAMES)

    def split(value: float, timestamp: datetime) -> PreparedSplit:
        return PreparedSplit(
            np.full((2, config.lookback_steps, width), value),
            np.array([value, value]),
            (timestamp, timestamp),
        )

    return PreparedDataset(
        feature_names=FEATURE_NAMES,
        target_name=TARGET_NAME,
        train=split(0.2, datetime(2026, 8, 1, 1, tzinfo=UTC)),
        validation=split(0.3, datetime(2026, 8, 1, 2, tzinfo=UTC)),
        test=split(0.4, datetime(2026, 8, 1, 3, tzinfo=UTC)),
        scaler=ScalerMetadata(
            feature_indices=tuple(FEATURE_NAMES.index(name) for name in CONTINUOUS_FEATURE_NAMES),
            means=(0.0,) * len(CONTINUOUS_FEATURE_NAMES),
            scales=(1.0,) * len(CONTINUOUS_FEATURE_NAMES),
        ),
        split_id="a" * 64,
        source_started_at=datetime(2026, 8, 1, tzinfo=UTC),
        source_ended_at=datetime(2026, 8, 1, 3, tzinfo=UTC),
        train_ended_at=datetime(2026, 8, 1, 1, tzinfo=UTC),
        validation_ended_at=datetime(2026, 8, 1, 2, tzinfo=UTC),
        config=config,
        slot_count=5,
    )


class ByteSavingModel:
    def __init__(self, contents: bytes = b"keras-model") -> None:
        self.contents = contents

    def save(self, path: Path) -> None:
        path.write_bytes(self.contents)


class RecordingBackend:
    def __init__(self) -> None:
        self.datasets: list[PreparedDataset] = []
        self.fit_calls: list[tuple[PreparedSplit, PreparedSplit, TrainingConfig]] = []
        self.prediction_inputs: list[np.ndarray] = []

    def build(self, config: TrainingConfig, dataset: PreparedDataset) -> ByteSavingModel:
        self.datasets.append(dataset)
        return ByteSavingModel(config.model.value.encode())

    def fit(
        self,
        model: ByteSavingModel,
        train: PreparedSplit,
        validation: PreparedSplit,
        config: TrainingConfig,
    ) -> None:
        self.fit_calls.append((train, validation, config))

    def predict(self, model: ByteSavingModel, inputs: np.ndarray) -> np.ndarray:
        self.prediction_inputs.append(inputs)
        return np.full((inputs.shape[0], 1), 0.4)

    def framework_versions(self) -> dict[str, str]:
        return {"tensorflow": "test", "keras": "test"}


def completed_metrics() -> EvaluationMetrics:
    return EvaluationMetrics(mae=0.1, mse=0.02, rmse=math.sqrt(0.02), inference_latency_ms=1.5)


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


def test_build_model_reports_actionable_missing_tensorflow(monkeypatch) -> None:
    monkeypatch.setattr(architectures, "_load_tensorflow", lambda: None)

    with pytest.raises(PredictionTrainingError) as raised:
        architectures.build_model(TrainingConfig(), (12, len(FEATURE_NAMES)))

    assert raised.value.code == "missing_ml_dependency"
    assert ".[ml]" in raised.value.message


@pytest.mark.ml
@pytest.mark.skipif(find_spec("tensorflow") is None, reason="TensorFlow is not installed")
@pytest.mark.parametrize("model", list(ModelFamily))
def test_real_architectures_emit_one_bounded_scalar(model: ModelFamily) -> None:
    built = architectures.build_model(
        TrainingConfig(model=model), (12, len(FEATURE_NAMES))
    )
    outputs = built(np.zeros((2, 12, len(FEATURE_NAMES))), training=False).numpy()

    assert outputs.shape == (2, 1)
    assert np.all((outputs >= 0) & (outputs <= 1))


def test_publish_artifact_hashes_model_and_writes_compatible_manifest(tmp_path) -> None:
    dataset = prepared_dataset()
    manifest_path = publish_artifact(
        ByteSavingModel(),
        dataset,
        TrainingConfig(),
        completed_metrics(),
        tmp_path,
        framework_versions={"tensorflow": "2.20", "keras": "3"},
        completed_at=datetime(2026, 9, 11, tzinfo=UTC),
    )
    payload = json.loads(manifest_path.read_text())
    artifact = tmp_path / payload["artifact_filename"]

    assert hashlib.sha256(artifact.read_bytes()).hexdigest() == payload["artifact_sha256"]
    assert payload["split_id"] == dataset.split_id
    assert tuple(payload["feature_names"]) == FEATURE_NAMES
    assert payload["lookback_steps"] == 12
    assert load_manifest(manifest_path, expected_dataset=dataset).model is ModelFamily.GRU


def test_publish_failure_leaves_no_discoverable_manifest(tmp_path) -> None:
    class FailedModel:
        def save(self, path: Path) -> None:
            raise OSError("disk stopped")

    with pytest.raises(PredictionTrainingError) as raised:
        publish_artifact(
            FailedModel(), prepared_dataset(), TrainingConfig(), completed_metrics(), tmp_path
        )

    assert raised.value.code == "artifact_write_failed"
    assert not list(tmp_path.glob("*.json"))


def test_manifest_loader_rejects_tampered_artifact(tmp_path) -> None:
    manifest_path = publish_artifact(
        ByteSavingModel(), prepared_dataset(), TrainingConfig(), completed_metrics(), tmp_path
    )
    manifest = json.loads(manifest_path.read_text())
    (tmp_path / manifest["artifact_filename"]).write_bytes(b"tampered")

    with pytest.raises(PredictionTrainingError) as raised:
        load_manifest(manifest_path, expected_dataset=prepared_dataset())

    assert raised.value.code == "artifact_mismatch"


def test_publish_replaces_corrupt_file_at_content_address(tmp_path) -> None:
    expected = b"expected-model"
    digest = hashlib.sha256(expected).hexdigest()
    artifact = tmp_path / f"{digest}.keras"
    tmp_path.mkdir(exist_ok=True)
    artifact.write_bytes(b"corrupt")

    publish_artifact(
        ByteSavingModel(expected),
        prepared_dataset(),
        TrainingConfig(),
        completed_metrics(),
        tmp_path,
    )

    assert artifact.read_bytes() == expected


def test_manifest_loader_wraps_malformed_metric_type(tmp_path) -> None:
    manifest_path = publish_artifact(
        ByteSavingModel(), prepared_dataset(), TrainingConfig(), completed_metrics(), tmp_path
    )
    payload = json.loads(manifest_path.read_text())
    payload["mae"] = "not-a-number"
    manifest_path.write_text(json.dumps(payload))

    with pytest.raises(PredictionTrainingError) as raised:
        load_manifest(manifest_path)

    assert raised.value.code == "invalid_manifest"


def test_manifest_loader_rejects_unsafe_path_and_dataset_mismatch(tmp_path) -> None:
    manifest_path = publish_artifact(
        ByteSavingModel(), prepared_dataset(), TrainingConfig(), completed_metrics(), tmp_path
    )
    payload = json.loads(manifest_path.read_text())
    payload["artifact_filename"] = "../outside.keras"
    manifest_path.write_text(json.dumps(payload))
    with pytest.raises(PredictionTrainingError) as unsafe:
        load_manifest(manifest_path, expected_dataset=prepared_dataset())
    assert unsafe.value.code == "invalid_manifest"

    manifest_path = publish_artifact(
        ByteSavingModel(), prepared_dataset(), TrainingConfig(), completed_metrics(), tmp_path
    )
    with pytest.raises(PredictionTrainingError) as mismatch:
        load_manifest(
            manifest_path,
            expected_dataset=replace(prepared_dataset(), split_id="b" * 64),
        )
    assert mismatch.value.code == "invalid_manifest"


def test_comparison_passes_same_dataset_to_every_model(tmp_path) -> None:
    dataset = prepared_dataset()
    backend = RecordingBackend()

    results = compare_models(
        dataset,
        default_comparison_configs(),
        tmp_path,
        _backend=backend,
    )

    assert len(backend.datasets) == 3
    assert all(received is dataset for received in backend.datasets)
    assert [result.model for result in results] == list(ModelFamily)
    assert all(result.split_id == dataset.split_id for result in results)


def test_training_preserves_split_roles_and_publishes_result(tmp_path) -> None:
    dataset = prepared_dataset()
    backend = RecordingBackend()

    result = train_model(dataset, TrainingConfig(), tmp_path, _backend=backend)

    train, validation, config = backend.fit_calls[0]
    assert train is dataset.train
    assert validation is dataset.validation
    assert config.model is ModelFamily.GRU
    assert all(inputs is dataset.test.inputs for inputs in backend.prediction_inputs)
    assert len(backend.prediction_inputs) == 1 + 1 + config.latency_repetitions
    assert result.metrics.mae == 0.0
    assert result.manifest_path.is_file()


@pytest.mark.parametrize(
    "configs",
    [
        (TrainingConfig(model=ModelFamily.LSTM),),
        (
            TrainingConfig(model=ModelFamily.LSTM),
            TrainingConfig(model=ModelFamily.LSTM),
            TrainingConfig(model=ModelFamily.TRANSFORMER),
        ),
    ],
)
def test_comparison_rejects_missing_or_duplicate_model_configs(tmp_path, configs) -> None:
    with pytest.raises(PredictionTrainingError) as raised:
        compare_models(prepared_dataset(), configs, tmp_path, _backend=RecordingBackend())

    assert raised.value.code == "invalid_training_config"


def test_comparison_returns_fixed_order_for_unordered_configs(tmp_path) -> None:
    configs = tuple(reversed(default_comparison_configs()))

    results = compare_models(
        prepared_dataset(), configs, tmp_path, _backend=RecordingBackend()
    )

    assert [result.model for result in results] == list(ModelFamily)
