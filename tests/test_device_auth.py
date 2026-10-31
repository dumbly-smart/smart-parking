from __future__ import annotations

import shutil
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.app.config import Settings
from backend.app.main import create_app


def write_settings_files(tmp_path: Path) -> Settings:
    config_path = tmp_path / "parking.yaml"
    shutil.copy(Path(__file__).resolve().parents[1] / "config/parking.yaml", config_path)
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'parking.db'}",
        parking_config_path=config_path,
    )


def test_device_token_protects_api_without_changing_local_health(tmp_path) -> None:
    settings = write_settings_files(tmp_path)
    settings.device_api_token = SecretStr("test-only-device-token")

    with TestClient(create_app(settings)) as client:
        health = client.get("/health")
        unauthorized = client.get("/api/parking/status")
        invalid = client.get(
            "/api/parking/status", headers={"Authorization": "Bearer wrong-token"}
        )
        authorized = client.get(
            "/api/parking/status",
            headers={"Authorization": "Bearer test-only-device-token"},
        )

    assert health.status_code == 200
    assert unauthorized.status_code == 401
    assert unauthorized.headers["www-authenticate"] == "Bearer"
    assert invalid.status_code == 401
    assert authorized.status_code == 200
