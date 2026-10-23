from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.hardware_evaluation import load_events, summarize, write_outputs


def test_summarize_reports_only_observed_hardware_events() -> None:
    events = [
        {"event": "rfid_trial", "success": True},
        {"event": "rfid_trial", "success": False},
        {"event": "rfid_read", "success": True},
        {"event": "api_transaction", "success": True, "operation": "entry", "latency_ms": 120},
        {"event": "api_transaction", "success": False, "operation": "exit", "latency_ms": 260},
        {"event": "gate_command", "operation": "entry", "latency_ms": 300},
        {"event": "free_heap", "free_heap_bytes": 64000},
        {
            "event": "camera_capture",
            "status": "success",
            "capture_latency_ms": 37,
            "jpeg_bytes": 12000,
        },
        {"event": "led_observation", "expected": True, "observed": False},
    ]

    metrics = summarize(events)["metrics"]

    assert metrics["rfid_read_success_rate"] == {
        "status": "MEASURED", "successes": 1, "trials": 2, "rate": 0.5
    }
    assert metrics["api_transaction_success_rate"]["rate"] == 0.5
    assert metrics["entry_response_latency_ms"]["mean"] == 120
    assert metrics["exit_response_latency_ms"]["p95"] == 260
    assert metrics["servo_command_delay_ms"]["median"] == 300
    assert metrics["free_heap_bytes"]["mean"] == 64000
    assert metrics["camera_capture_latency_ms"]["mean"] == 37
    assert metrics["camera_capture_success_rate"]["rate"] == 1
    assert metrics["led_correctness_rate"]["rate"] == 0
    assert metrics["camera_processing_latency_ms"] == {"status": "NOT TESTED", "count": 0}


def test_wifi_recovery_uses_host_capture_timestamps() -> None:
    events = [
        {"event": "wifi_disconnected", "host_received_at_utc": "2026-10-20T10:00:00Z"},
        {"event": "wifi_connected", "host_received_at_utc": "2026-10-20T10:00:07Z"},
    ]

    metric = summarize(events)["metrics"]["wifi_recovery_seconds"]

    assert metric["status"] == "MEASURED"
    assert metric["mean"] == 7


def test_load_events_rejects_malformed_json(tmp_path: Path) -> None:
    source = tmp_path / "events.jsonl"
    source.write_text('{"event":"ok"}\nnot json\n', encoding="utf-8")

    with pytest.raises(ValueError, match="line 2"):
        load_events(source)


def test_write_outputs_preserves_provenance_and_not_tested_status(tmp_path: Path) -> None:
    source = tmp_path / "events.jsonl"
    line = json.dumps({"event": "controller_boot", "uptime_ms": 1}) + "\n"
    source.write_text(line, encoding="utf-8")
    output = tmp_path / "results"

    csv_path, json_path = write_outputs(source, output)
    report = json.loads(json_path.read_text(encoding="utf-8"))

    assert csv_path.read_text(encoding="utf-8").startswith("event,")
    assert report["provenance"].startswith("captured hardware serial")
    assert report["metrics"]["power_current_ma"]["status"] == "NOT TESTED"
