from __future__ import annotations

from pathlib import Path

import scripts.train_prediction_models as train_script
from backend.app.db import Database
from prediction.training import EvaluationMetrics, ModelFamily, TrainingResult
from scripts.seed_prediction_demo_data import main
from scripts.train_prediction_models import main as train_main


def test_seed_demo_command_reports_counts_without_rfid(tmp_path, capsys) -> None:
    database_url = f"sqlite:///{tmp_path / 'prediction-demo.db'}"

    assert main(["--database-url", database_url, "--days", "7", "--seed", "11"]) == 0

    output = capsys.readouterr().out
    assert '"context_samples": 2016' in output
    assert '"sessions":' in output
    assert "rfid" not in output.lower()
    assert "demo-rfid" not in output


def test_train_command_reports_actionable_missing_ml_dependency(
    tmp_path, capsys, monkeypatch
) -> None:
    from prediction.training import PredictionTrainingError

    database_url = f"sqlite:///{tmp_path / 'prediction-demo.db'}"
    assert main(["--database-url", database_url, "--days", "1", "--seed", "11"]) == 0
    capsys.readouterr()

    def missing_tensorflow():
        raise PredictionTrainingError(
            "missing_ml_dependency",
            "TensorFlow is required for training; install it with pip install -e '.[ml]'",
        )

    monkeypatch.setattr("prediction.architectures._require_tensorflow", missing_tensorflow)

    exit_code = train_main(
        [
            "--database-url",
            database_url,
            "--artifact-directory",
            str(tmp_path / "artifacts"),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert ".[ml]" in captured.err


def test_train_command_persists_completed_comparison_after_training(tmp_path, monkeypatch) -> None:
    database_url = f"sqlite:///{tmp_path / 'prediction-demo.db'}"
    assert main(["--database-url", database_url, "--days", "7", "--seed", "11"]) == 0
    result = TrainingResult(
        model=ModelFamily.GRU,
        split_id="a" * 64,
        metrics=EvaluationMetrics(mae=0.1, mse=0.02, rmse=0.14, inference_latency_ms=1.0),
        manifest_path=Path("artifact.json"),
    )
    saved: list[object] = []

    monkeypatch.setattr(train_script, "compare_models", lambda *_: (result,))
    monkeypatch.setattr(Database, "save_prediction_results", lambda _, rows: saved.extend(rows))

    assert (
        train_script.main(
            ["--database-url", database_url, "--artifact-directory", str(tmp_path / "artifacts")]
        )
        == 0
    )

    assert saved == [result]
