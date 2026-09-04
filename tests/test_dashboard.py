from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app


def make_settings(tmp_path: Path) -> Settings:
    config_path = tmp_path / "parking.yaml"
    config_path.write_text(
        """allocation:
  weights: {distance: 0.35, congestion: 0.30, waiting: 0.20, fairness: 0.15}
slots:
  - {id: 1, name: S1, walking_distance: 0.2, zone: north}
  - {id: 2, name: S2, walking_distance: 0.3, zone: north}
  - {id: 3, name: S3, walking_distance: 0.5, zone: central}
  - {id: 4, name: S4, walking_distance: 0.7, zone: south}
  - {id: 5, name: S5, walking_distance: 0.9, zone: south}
""",
        encoding="utf-8",
    )
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'parking.db'}",
        parking_config_path=config_path,
    )


def test_dashboard_serves_semantic_local_document(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path))) as client:
        response = client.get("/dashboard")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert '<main id="dashboard"' in response.text
    assert 'src="/static/dashboard/dashboard.js"' in response.text
    assert 'href="/static/dashboard/dashboard.css"' in response.text
    assert "https://" not in response.text


@pytest.mark.parametrize(
    ("path", "content_type"),
    [
        ("/static/dashboard/dashboard.css", "text/css"),
        ("/static/dashboard/dashboard.js", "text/javascript"),
    ],
)
def test_dashboard_assets_are_served(
    tmp_path: Path, path: str, content_type: str
) -> None:
    with TestClient(create_app(make_settings(tmp_path))) as client:
        response = client.get(path)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(content_type)
