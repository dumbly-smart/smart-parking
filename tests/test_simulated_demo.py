from __future__ import annotations

import json
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from scripts.run_simulated_demo import main


class SimulatedApi:
    def __init__(self) -> None:
        self.paths: list[str] = []
        self.allocation_payload: dict[str, object] | None = None
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                owner.paths.append(self.path)
                if self.path == "/api/parking/status":
                    self._reply(
                        {
                            "slots": [
                                {
                                    "id": 1,
                                    "name": "Bay 1",
                                    "walking_distance": 0.2,
                                    "zone": "north",
                                    "occupied": True,
                                    "updated_at": "2026-09-12T10:00:00Z",
                                    "active_session_id": 7,
                                    "rfid_uid": "CARD-PRIVATE",
                                },
                                {
                                    "id": 2,
                                    "name": "Bay 2",
                                    "walking_distance": 0.8,
                                    "zone": "south",
                                    "occupied": False,
                                    "updated_at": "2026-09-12T10:00:00Z",
                                    "active_session_id": None,
                                    "rfid_uid": None,
                                },
                            ]
                        }
                    )
                elif self.path == "/api/prediction":
                    self._reply(
                        {
                            "model": "baseline",
                            "occupancy_ratio": 0.5,
                            "target_at": "2026-09-12T10:05:00Z",
                            "fallback_reason": "insufficient_history",
                        }
                    )
                else:
                    self.send_error(404)

            def do_POST(self) -> None:
                owner.paths.append(self.path)
                size = int(self.headers["Content-Length"])
                body = self.rfile.read(size)
                if self.path == "/api/camera/occupancy":
                    assert self.headers["Content-Type"].startswith("multipart/form-data")
                    self._reply(
                        {
                            "detector": "heuristic",
                            "observed_at": "2026-09-12T10:00:00Z",
                            "slots": [],
                        }
                    )
                elif self.path == "/api/vehicle/entry":
                    assert json.loads(body) == {
                        "rfid_uid": "CARD-PRIVATE",
                        "idempotency_key": "demo-entry-1",
                    }
                    self._reply(
                        {
                            "session_id": 7,
                            "rfid_uid": "CARD-PRIVATE",
                            "slot_id": 1,
                            "slot_name": "Bay 1",
                            "optimizer": "ga",
                            "allocation_cost": 0.2,
                            "entered_at": "2026-09-12T10:00:00Z",
                            "gate_action": "open",
                        }
                    )
                elif self.path == "/api/allocation/run":
                    owner.allocation_payload = json.loads(body)
                    self._reply(
                        {
                            "results": [
                                {
                                    "algorithm": "ga",
                                    "scenario_id": "simulated-demo",
                                    "chosen_slot_id": 2,
                                    "best_cost": 0.1,
                                    "iterations": 30,
                                    "runtime_ms": 1.2,
                                    "objective_breakdown": {
                                        "distance": 0.8,
                                        "congestion": 0.0,
                                        "waiting": 0.0,
                                        "fairness": 0.0,
                                    },
                                    "seed": 20260912,
                                }
                            ]
                        }
                    )
                else:
                    self.send_error(404)

            def _reply(self, payload: object) -> None:
                encoded = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = Thread(target=self.server.serve_forever)

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()


@pytest.fixture
def simulated_api() -> Iterator[SimulatedApi]:
    server = SimulatedApi()
    server.start()
    try:
        yield server
    finally:
        server.stop()


def test_demo_calls_existing_apis_and_redacts_rfid(
    simulated_api: SimulatedApi, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        [
            "--base-url",
            simulated_api.base_url,
            "--rfid-uid",
            "CARD-PRIVATE",
            "--idempotency-key",
            "demo-entry-1",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert simulated_api.paths == [
        "/api/camera/occupancy",
        "/api/camera/occupancy",
        "/api/camera/occupancy",
        "/api/vehicle/entry",
        "/api/parking/status",
        "/api/allocation/run",
        "/api/prediction",
        "/api/parking/status",
    ]
    assert simulated_api.allocation_payload == {
        "algorithm": "all",
        "request": {
            "scenario_id": "simulated-demo",
            "candidates": [
                {
                    "slot_id": 1,
                    "occupied": True,
                    "distance": 0.2,
                    "congestion": 1.0,
                    "waiting": 0.0,
                    "fairness": 0.0,
                },
                {
                    "slot_id": 2,
                    "occupied": False,
                    "distance": 0.8,
                    "congestion": 0.0,
                    "waiting": 0.0,
                    "fairness": 0.0,
                },
            ],
            "weights": {"distance": 0.35, "congestion": 0.3, "waiting": 0.2, "fairness": 0.15},
            "seed": 20260912,
            "iterations": 30,
        },
    }
    assert "CARD-PRIVATE" not in output
    assert json.loads(output)["entry_slot"] == "Bay 1"
