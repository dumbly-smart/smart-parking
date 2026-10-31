# Hardware measurements and validation

The latest controller trial was captured on 2026-10-26 after correcting the ESP32 Wi-Fi SSID and the backend host address, restarting the authenticated hardware API, and flashing the controller firmware. The serial capture records two operator-confirmed test-tag scans, two RFID reads, and successful entry and exit transactions (HTTP 200 for both). The measured entry API latency was 1,431 ms and exit latency was 1,220 ms (one trial each). Status telemetry showed S1 occupied after entry and free after exit; all five initial free-slot outputs were commanded off.

Four firmware gate-command timestamps were recorded: 3,300, 5,800, 3,200, and 6,144 ms from scan start. These are controller command timings, not measured servo travel. Free heap across eight serial events averaged 237,202 bytes (median 237,304; sample standard deviation 1,027; p95 238,352). Two RFID trials are not a reliability estimate.

The serial log does not verify visible LED light output or mechanical servo movement. Wi-Fi recovery duration and current draw were not measured. Earlier RC522 VersionReg probes of `0xFF` and `0x00` predate the rewiring and successful test-tag transactions.

`live_controller_20261026_verified.jsonl` is the raw serial capture. `hardware_measurements_20261026.jsonl`, `hardware_events.csv`, and `hardware_summary.json` include the captured events and two operator-confirmed trial-denominator records. RFID identifiers and credentials are not logged. A missing metric means no valid sample was recorded; it does not mean zero latency, zero power, or a successful physical observation. See `docs/hardware/measurement_procedure.md` for repeatable procedures and `controller_validation.json` for board and flash details.
