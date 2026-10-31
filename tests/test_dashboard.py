from __future__ import annotations

import json
import re
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app


def make_settings(
    tmp_path: Path,
    *,
    slot_ids: tuple[int, ...] = (1, 2, 3, 4, 5),
    selected_optimizer: str = "ga",
    selected_predictor: str = "baseline",
) -> Settings:
    parking_path = tmp_path / "parking.yaml"
    parking_path.write_text(
        yaml.safe_dump(
            {
                "allocation": {
                    "weights": {
                        "distance": 0.35,
                        "congestion": 0.30,
                        "waiting": 0.20,
                        "fairness": 0.15,
                    }
                },
                "slots": [
                    {
                        "id": slot_id,
                        "name": f"Bay {slot_id}",
                        "walking_distance": index / (len(slot_ids) + 1),
                        "zone": "north" if index % 2 else "south",
                    }
                    for index, slot_id in enumerate(slot_ids, start=1)
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'parking.db'}",
        parking_config_path=parking_path,
        selected_optimizer=selected_optimizer,
        selected_predictor=selected_predictor,
        prediction_artifact_directory=tmp_path / "artifacts",
    )


def test_dashboard_serves_safe_bootstrap_and_assets(tmp_path: Path) -> None:
    settings = make_settings(
        tmp_path,
        selected_optimizer="pso",
        selected_predictor="gru",
    )

    with TestClient(create_app(settings)) as client:
        page = client.get("/dashboard")
        stylesheet = client.get("/static/dashboard.css")
        javascript = client.get("/static/dashboard.js")

    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert 'id="dashboard-bootstrap"' in page.text
    assert '"selected_optimizer": "pso"' in page.text
    assert '"selected_predictor": "gru"' in page.text
    bootstrap = re.search(
        r'<script id="dashboard-bootstrap" type="application/json">(.*?)</script>',
        page.text,
    )
    assert bootstrap is not None
    bootstrap_data = json.loads(bootstrap.group(1))
    assert set(bootstrap_data) == {
        "selected_optimizer",
        "selected_predictor",
        "predictor_comparison",
        "scene",
    }
    assert len(bootstrap_data["predictor_comparison"]) == 4
    assert bootstrap_data["scene"]["asset"] is None
    assert set(bootstrap_data["scene"]["slots"]) == {"1", "2", "3", "4", "5"}
    assert stylesheet.status_code == 200
    assert javascript.status_code == 200
    assert "Compare live bay assignment with GA, PSO, ACO, and NSGA-II" in page.text
    assert "Running GA, PSO, ACO, and NSGA-II" in javascript.text


def test_dashboard_supports_dynamic_slots_and_uses_privacy_safe_assets(
    tmp_path: Path,
) -> None:
    settings = make_settings(tmp_path, slot_ids=(9, 2, 14))

    with TestClient(create_app(settings)) as client:
        entered = client.post(
            "/api/vehicle/entry",
            json={"rfid_uid": "CARD-PRIVATE", "idempotency_key": "entry-1"},
        )
        status = client.get("/api/parking/status")
        page = client.get("/dashboard")
        javascript = client.get("/static/dashboard.js")

    assert entered.status_code == 200
    assert [slot["id"] for slot in status.json()["slots"]] == [9, 2, 14]
    assert 'id="slot-grid"' in page.text
    assert "CARD-PRIVATE" not in page.text
    assert "CARD-PRIVATE" not in javascript.text


def test_dashboard_data_apis_remain_compatible_with_prediction_fallback(
    tmp_path: Path,
) -> None:
    settings = make_settings(tmp_path, slot_ids=(4, 8))

    with TestClient(create_app(settings)) as client:
        status = client.get("/api/parking/status")
        optimizers = client.get("/api/benchmarks/optimizers")
        predictors = client.get("/api/benchmarks/predictors")
        prediction = client.get("/api/prediction")

    assert status.status_code == 200
    assert len(status.json()["slots"]) == 2
    assert optimizers.json() == {"runs": []}
    assert predictors.json() == {"runs": []}
    assert prediction.status_code == 200
    assert prediction.json()["model"] == "baseline"
    assert prediction.json()["fallback_reason"] == "insufficient_history"
    assert prediction.json()["target_at"]


def test_dashboard_has_labeled_predictor_comparison_when_runtime_has_no_runs(
    tmp_path: Path,
) -> None:
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        benchmarks = client.get("/api/benchmarks/predictors")
        page = client.get("/dashboard")
        javascript = client.get("/static/dashboard.js")

    assert benchmarks.json() == {"runs": []}
    assert 'id="predictor-provenance"' in page.text
    assert 'id="predictor-source" class="comparison-source">ACTUAL TEST RESULTS</span>' in page.text
    assert "synthetic dataset" in page.text
    assert "0.120875" in page.text
    assert "0.028620" in page.text
    assert "0.169173" in page.text
    assert "0.098055" in page.text
    assert "0.013891" in page.text
    assert "0.117862" in page.text
    assert "0.223783 ms" in page.text
    assert "bootstrap.predictor_comparison" in javascript.text
    assert "STORED_PREDICTOR_RESULTS" in javascript.text
    assert "persistence_baseline" in page.text
    assert "synthetic" in javascript.text.lower()
