from __future__ import annotations

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


def test_train_command_reports_actionable_missing_ml_dependency(tmp_path, capsys) -> None:
    database_url = f"sqlite:///{tmp_path / 'prediction-demo.db'}"
    assert main(["--database-url", database_url, "--days", "1", "--seed", "11"]) == 0
    capsys.readouterr()

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
