# Final completion audit

Audit date: 2026-10-20. This inventory distinguishes source-level behavior,
automated software evidence, compile evidence, and physical measurements.
Compilation and simulated API traffic do not establish that a circuit works.
Final repository checks for this audit completed with 257 passing software
tests, clean Ruff lint, both firmware builds, successful report generation,
matching diagram pin validation, and clean `git diff --check`.

## Fully implemented and software-tested

- FastAPI and SQLite provide configured parking slots, health/status, atomic
  vehicle entry/exit, persistent cross-operation idempotency, conflict/full
  capacity handling, event history, and optimizer/predictor APIs.
- Dashboard state is driven by parking status and the durable server event
  stream. Event payloads sent to browsers redact RFID UIDs. The existing GLB
  scene and vehicle animations remain in place.
- The deterministic software demo exercises three synthetic JPEG occupancy
  requests, a vehicle entry, optimizer comparisons, a forecast, and final slot
  status. It completed against an isolated temporary database during this
  audit; the running application database was not changed.
- Camera ingestion bounds frame sizes, validates JPEG responses, applies the
  five configured ROIs, filters low-confidence observations, smooths repeated
  observations, and prevents camera changes from clearing an active RFID
  session. Camera disconnect, malformed response, MIME, frame, calibration,
  and state-reconciliation cases have automated coverage.
- Prediction preprocessing retains the chronological 70/15/15 split,
  12-bucket lookback, 27 features, training-only normalization, shared test
  split, persistence baseline, and regression metrics. Stored comparison
  results include LSTM, GRU, and Transformer MAE/MSE/RMSE, server inference
  latency, and model size. Artifacts were previously reloaded and checked
  against their manifests and hashes. The review report labels its data
  synthetic and its timings server-side.
- Allocation uses `0.35D + 0.30G + 0.20W + 0.15F`, occupied-slot feasibility,
  common scenario inputs and seeds. The stored benchmark compares first
  available, exhaustive enumeration, GA, PSO, and ACO; exhaustive enumeration
  is the exact one-slot optimum for the small candidate set. The five-slot
  heuristic comparison is not evidence of real traffic throughput.
- A reproducible hardware evaluation CLI now captures controller/camera JSON
  serial events and operator observations, writes CSV/JSON summaries, calculates
  numeric descriptive statistics, and marks unobserved metrics `NOT TESTED`.
  The occupancy API also returns its measured processing duration in headers,
  and the camera poller can persist it. The controller and camera firmware emit
  privacy-safe event lines; none records card UIDs, credentials, network
  addresses, or image contents. The initial empty harness output was replaced on 2026-10-21 with physical
  controller boot/reader events and API access-log evidence in `output/hardware/`.
  Free heap is measured at boot; RFID, camera, actuation, current, and visual
  quantitative measurements remain `NOT TESTED` as described below. The user
  later reported that the assembled tabletop hardware works; no post-rewire
  trial log or component-level measurement accompanied that report.
- Editable black-and-white Graphviz block, wiring, and circuit diagrams,
  monochrome SVG/PNG/A4 PDF exports, pin CSV, and BOM are present. The validator
  matched all 29 documented GPIO assignments to the firmware header values.
- The current final report source generates an editable A4 DOCX and PDF in
  `output/final_submission/`; its abstract is 250 words, it has nine keywords,
  five verified recent references, grayscale figures, and the supplied student
  details. The separate root clean PDF and existing review report files were
  preserved.

## Implemented but not sufficiently tested on target hardware

- Controller Wi-Fi connect/reconnect, UID normalization, held-card suppression,
  NVS idempotency recovery, server response validation, confirmed assignment,
  unknown-state LED indication, OLED feedback, LED mapping, and fail-closed
  servo logic compile. The ESP32 controller was flashed and booted. Wi-Fi connected twice, and the
  protected server logged successful health and parking-status requests from
  the device. RC522 boot diagnostics before the user's later successful hardware
  check read VersionReg `0xFF`, then `0x00` after the first rewiring attempt.
  These are historical pre-fix probes; the user subsequently reported the rig
  works. No post-rewire card-read log, OLED/LED visual record, gate timing, or
  quantitative trial count is available.
- Camera firmware initializes the AI-Thinker OV2640, exposes bounded
  `/health` and `/capture` responses, retries incomplete JPEG writes, and emits
  capture timing/size/heap metrics. No camera board was found on the local network; no physical frame or scene
  calibration was captured.
- The edge-density detector is a deterministic baseline, not a learned
  classifier. No real labeled scene set was found, so field occupancy accuracy
  cannot be calculated. A neural classifier has not been added without data.
- Automated backend tests cover API lifecycle, idempotency, concurrency,
  conflict handling, dashboard/event synchronization, image validation, and
  recovery paths. They do not emulate real firmware timing, RF reads, motor
  motion, power draw, electrical noise, or boot behavior.
- Source-contract tests check fail-closed response validation, persisted-key
  ordering, duplicate gate-actuation guard, Wi-Fi unknown-state behavior, and
  serial privacy. These are static source checks, not firmware runtime tests.
- Controller firmware compiled and was flashed with hash verification to the
  identified ESP32-D0WD-V3 board. The 4 MiB flash was backed up before update.
  Camera firmware is compile-only; the camera board was not found or flashed.

## Missing or blocked functionality

- Local integration is configured on this workstation. Ignored mode-0600 firmware
  configs use the active private Wi-Fi profile, and a user systemd service binds
  the token-protected hardware API to this host's current Wi-Fi address on port
  8001. The dashboard/development service remains on loopback port 8000. This
  address and service bind must be updated if the Wi-Fi address changes.
- The host exposes `/dev/ttyUSB0` through a `1a86` USB serial bridge owned by
  group `uucp`; the current user is not in that group. This identifies a serial
  adapter; read-only esptool identification confirmed an ESP32-D0WD-V3, revision
  3.1. Host serial access is blocked by local permissions, but device passthrough
  in Docker enabled a full backup, flash, and serial capture.
- The hardware service uses bearer authentication for `/api/*`, but traffic has
  no TLS. Physical operation must use a restricted trusted LAN; do not expose
  the service publicly. `/health` is unauthenticated and exposes basic health
  only.
- No board reset-mid-request, Wi-Fi outage/recovery trial, duplicate RFID tap,
  entry/exit transaction, full-lot gate behavior, servo timing, camera operation,
  LED/OLED visual check, current draw, or memory-under-load measurement has been
  recorded. The RC522 returned version register `0xFF`; the wiring still requires
  correction before card testing.
- Hardware metrics not received from real serial capture or operator
  observations remain `NOT TESTED`; no synthetic figure is substituted.

## Academic deliverables needing revision or manual confirmation

- Fill institution, course, and faculty/guide fields and apply the professor's
  official base-paper template if required; none was present in the repository.
- Verify the institution-restricted Drive links from the professor's account.
  Public dataset access is version-pinned in the report; Drive permission is a
  submission-time manual check.
- The report was rebuilt after the integration changes but before the controller
  hardware measurements; regenerate it after physical tests are complete. Review
  page layout,
  author details, references, and figure legibility against institutional
  requirements.
- Update hardware results and report/checklist only after collecting genuine
  measurements. The report must continue distinguishing synthetic experiments
  and software timing from hardware measurements.

## Current evidence paths

- Software tests: `tests/`, including `tests/test_hardware_evaluation.py`.
- Synthetic ML and optimization results: `review_outputs/2026-10-15/`.
- Firmware source and build targets: `firmware/esp32_controller/` and
  `firmware/esp32_cam/`.
- Proposed hardware package: `docs/hardware/` and
  `scripts/validate_hardware_diagrams.py`.
- Physical evaluation procedure: `docs/hardware/measurement_procedure.md`.
- Final report and evidence copies: `output/final_submission/`.
- Remaining actions: `output/final_submission/SUBMISSION_CHECKLIST.md`.
