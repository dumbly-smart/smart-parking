from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

EVENT_FIELDS = (
    "event",
    "host_received_at_utc",
    "uptime_ms",
    "operation",
    "success",
    "latency_ms",
    "http_status",
    "slot_id",
    "gate",
    "expected",
    "observed",
    "free_heap_bytes",
    "capture_bytes",
    "capture_latency_ms",
    "jpeg_bytes",
    "sent_bytes",
    "reason",
    "current_ma",
    "raw_json",
)
METRICS = (
    "rfid_read_success_rate",
    "api_transaction_success_rate",
    "camera_capture_success_rate",
    "entry_response_latency_ms",
    "exit_response_latency_ms",
    "led_correctness_rate",
    "wifi_recovery_seconds",
    "servo_command_delay_ms",
    "camera_capture_latency_ms",
    "camera_processing_latency_ms",
    "free_heap_bytes",
    "power_current_ma",
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def capture(port: str, baud: int, destination: Path, duration: float | None) -> int:
    try:
        import serial
    except ImportError:
        print(
            "Install hardware tools with: python -m pip install -e '.[hardware]'",
            file=sys.stderr,
        )
        return 2

    destination.parent.mkdir(parents=True, exist_ok=True)
    started = datetime.now(UTC).timestamp()
    try:
        with serial.Serial(port, baudrate=baud, timeout=1) as device, destination.open(
            "a", encoding="utf-8"
        ) as output:
            print(f"Recording {port} at {baud} baud to {destination}; Ctrl-C stops capture.")
            while duration is None or datetime.now(UTC).timestamp() - started < duration:
                raw = device.readline()
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="replace").strip()
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict) or not isinstance(event.get("event"), str):
                    continue
                event["host_received_at_utc"] = _utc_now()
                output.write(json.dumps(event, sort_keys=True) + "\n")
                output.flush()
    except KeyboardInterrupt:
        return 0
    except (OSError, serial.SerialException) as exc:
        print(f"Cannot capture from {port}: {exc}", file=sys.stderr)
        return 2
    return 0


def load_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"line {line_number} is not valid JSON: {exc.msg}") from exc
            if not isinstance(value, dict) or not isinstance(value.get("event"), str):
                raise ValueError(f"line {line_number} must be an event object with an event name")
            events.append(value)
    return events


def _stats(values: list[float]) -> dict[str, float | int]:
    ordered = sorted(values)
    p95_index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return {
        "count": len(ordered),
        "mean": statistics.fmean(ordered),
        "median": statistics.median(ordered),
        "standard_deviation": statistics.stdev(ordered) if len(ordered) > 1 else 0.0,
        "p95": ordered[p95_index],
    }


def summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    values: dict[str, list[float]] = defaultdict(list)
    outcomes: dict[str, list[bool]] = defaultdict(list)
    wifi_down: datetime | None = None
    for event in events:
        kind = event["event"]
        success = event.get("success")
        if isinstance(success, bool):
            # rfid_read records detected cards. Only operator-entered rfid_trial
            # events have a denominator and can support a read-success rate.
            if kind == "rfid_trial":
                outcomes["rfid_read_success_rate"].append(success)
            if kind in {"api_transaction", "api_result"}:
                outcomes["api_transaction_success_rate"].append(success)
            if kind == "camera_capture":
                outcomes["camera_capture_success_rate"].append(success)
        elif kind == "camera_capture" and isinstance(event.get("status"), str):
            outcomes["camera_capture_success_rate"].append(event["status"] == "success")
        latency = _number(event.get("latency_ms", event.get("capture_latency_ms")))
        operation = event.get("operation")
        if latency is not None:
            if kind in {"api_transaction", "api_result"} and operation in {"entry", "exit"}:
                values[f"{operation}_response_latency_ms"].append(latency)
            elif kind in {"camera_frame", "camera_capture"}:
                values["camera_capture_latency_ms"].append(latency)
            elif kind == "camera_processing":
                values["camera_processing_latency_ms"].append(latency)
            elif kind in {"gate_timing", "gate_command"}:
                values["servo_command_delay_ms"].append(latency)
        if kind == "led_observation" and "expected" in event and "observed" in event:
            outcomes["led_correctness_rate"].append(event["expected"] == event["observed"])
        if kind == "wifi_disconnected":
            try:
                timestamp = str(event["host_received_at_utc"]).replace("Z", "+00:00")
                wifi_down = datetime.fromisoformat(timestamp)
            except (KeyError, ValueError):
                wifi_down = None
        elif kind == "wifi_connected" and wifi_down is not None:
            try:
                timestamp = str(event["host_received_at_utc"]).replace("Z", "+00:00")
                connected = datetime.fromisoformat(timestamp)
                values["wifi_recovery_seconds"].append((connected - wifi_down).total_seconds())
            except (KeyError, ValueError):
                pass
            wifi_down = None
        free_heap = _number(event.get("free_heap_bytes"))
        if free_heap is not None:
            values["free_heap_bytes"].append(free_heap)
        current = _number(event.get("current_ma"))
        if current is not None:
            values["power_current_ma"].append(current)

    metrics: dict[str, Any] = {}
    for name in METRICS:
        if outcomes.get(name):
            outcomes_for_metric = outcomes[name]
            metrics[name] = {
                "status": "MEASURED",
                "successes": sum(outcomes_for_metric),
                "trials": len(outcomes_for_metric),
                "rate": sum(outcomes_for_metric) / len(outcomes_for_metric),
            }
        elif values.get(name):
            metrics[name] = {"status": "MEASURED", **_stats(values[name])}
        else:
            metrics[name] = {"status": "NOT TESTED", "count": 0}
    return {
        "schema_version": 1,
        "provenance": "captured hardware serial events and operator-entered observations",
        "generated_at_utc": _utc_now(),
        "event_count": len(events),
        "metrics": metrics,
    }


def write_outputs(events_path: Path, output_directory: Path) -> tuple[Path, Path]:
    events = load_events(events_path)
    output_directory.mkdir(parents=True, exist_ok=True)
    csv_path = output_directory / "hardware_events.csv"
    json_path = output_directory / "hardware_summary.json"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=EVENT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for event in events:
            writer.writerow({**event, "raw_json": json.dumps(event, sort_keys=True)})
    content = json.dumps(summarize(events), indent=2, sort_keys=True) + "\n"
    json_path.write_text(content, encoding="utf-8")
    return csv_path, json_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Capture and summarize genuine parking hardware measurements."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    capture_parser = commands.add_parser(
        "capture", help="capture JSON metric lines from an ESP32 serial port"
    )
    capture_parser.add_argument("--port", required=True)
    capture_parser.add_argument("--baud", type=int, default=115200)
    capture_parser.add_argument("--duration-seconds", type=float)
    capture_parser.add_argument("--output", type=Path, required=True)
    summary_parser = commands.add_parser(
        "summarize", help="export event CSV and measured/NOT TESTED JSON"
    )
    summary_parser.add_argument("--input", type=Path, required=True)
    summary_parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "capture":
        if args.baud <= 0 or (args.duration_seconds is not None and args.duration_seconds <= 0):
            parser.error("baud and duration must be positive")
        return capture(args.port, args.baud, args.output, args.duration_seconds)
    try:
        csv_path, json_path = write_outputs(args.input, args.output_directory)
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps({"csv": str(csv_path), "json": str(json_path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
