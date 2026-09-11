from __future__ import annotations

from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from backend.app.config import Settings, SlotConfig
from backend.app.db import Database
from backend.app.main import create_app
from backend.app.services.prediction import PredictionService
from prediction.artifacts import publish_artifact
from prediction.data import prepare_prediction_dataset
from prediction.demo_data import DemoDataConfig, replace_prediction_demo_data
from prediction.training import (
    EvaluationMetrics,
    ModelFamily,
    TrainingConfig,
    TrainingResult,
)


class ByteSavingModel:
    def save(self, path: Path) -> None:
        path.write_bytes(b"keras-model")


class LoadedModel:
    def __init__(self) -> None:
        self.calls = 0

    def predict(self, inputs: np.ndarray, verbose: int = 0) -> np.ndarray:
        self.calls += 1
        return np.array([[0.75]], dtype=np.float64)


def seeded_database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "prediction.db")
    database.initialize(
        [
            SlotConfig(id=1, name="S1", walking_distance=0.2, zone="north"),
            SlotConfig(id=2, name="S2", walking_distance=0.8, zone="south"),
        ]
    )
    replace_prediction_demo_data(
        database,
        DemoDataConfig(dataset_key="runtime", seed=11, days=7),
    )
    return database


def persist_gru_artifact(database: Database, artifact_directory: Path) -> None:
    dataset = prepare_prediction_dataset(database.load_prediction_source_data())
    metrics = EvaluationMetrics(mae=0.1, mse=0.02, rmse=0.14, inference_latency_ms=1.0)
    manifest_path = publish_artifact(
        ByteSavingModel(),
        dataset,
        TrainingConfig(model=ModelFamily.GRU),
        metrics,
        artifact_directory,
    )
    database.save_prediction_results(
        (TrainingResult(ModelFamily.GRU, dataset.split_id, metrics, manifest_path),)
    )


def test_runtime_uses_validated_artifact_and_caches_one_target_bucket(tmp_path: Path) -> None:
    database = seeded_database(tmp_path)
    artifacts = tmp_path / "artifacts"
    persist_gru_artifact(database, artifacts)
    loaded = LoadedModel()
    service = PredictionService(database, "gru", artifacts, _model_loader=lambda _: loaded)

    first = service.forecast()
    second = service.forecast()

    assert first.model == "gru"
    assert first.occupancy_ratio == 0.75
    assert first.target_at.minute % 5 == 0
    assert first == second
    assert loaded.calls == 1


def test_runtime_rejects_tampered_artifact_before_loading_and_uses_baseline(tmp_path: Path) -> None:
    database = seeded_database(tmp_path)
    artifacts = tmp_path / "artifacts"
    persist_gru_artifact(database, artifacts)
    artifact = next(artifacts.glob("*.keras"))
    artifact.write_bytes(b"tampered")
    loader_calls = 0

    def loader(_: Path) -> LoadedModel:
        nonlocal loader_calls
        loader_calls += 1
        return LoadedModel()

    result = PredictionService(database, "gru", artifacts, _model_loader=loader).forecast()

    assert result.model == "baseline"
    assert result.fallback_reason == "invalid_artifact"
    assert loader_calls == 0


def test_prediction_and_predictor_benchmark_apis_exclude_rfid_data(tmp_path: Path) -> None:
    database = seeded_database(tmp_path)
    artifacts = tmp_path / "artifacts"
    persist_gru_artifact(database, artifacts)
    settings = Settings(
        database_url=f"sqlite:///{database.path}",
        selected_predictor="baseline",
        prediction_artifact_directory=artifacts,
    )

    with TestClient(create_app(settings)) as client:
        forecast = client.get("/api/prediction")
        benchmarks = client.get("/api/benchmarks/predictors")

    assert forecast.status_code == 200
    assert forecast.json()["model"] == "baseline"
    assert benchmarks.status_code == 200
    assert benchmarks.json()["runs"][0]["model"] == "gru"
    assert "rfid" not in (forecast.text + benchmarks.text).lower()
