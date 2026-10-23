from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.app.main import create_app
from tests.test_occupancy_api import write_settings_files


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
