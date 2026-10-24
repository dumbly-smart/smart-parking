# Smart Parking Project Progress

Last updated: 2026-10-20

## Current Status

The framework-free dashboard and hardware-independent end-to-end demo are
complete. Shared preprocessing, deterministic demo history, common
LSTM/GRU/Transformer training, evaluation, schema-v2 artifact contracts, atomic
comparison persistence, runtime/comparison APIs, and live dashboard views are
implemented.

## Milestones

| Milestone | Status | Evidence / exit condition |
| --- | --- | --- |
| Design captured | Complete | `2026-09-03-smart-parking-design.md` |
| Architecture summarized | Complete | `architecture.md` |
| Agent workflow documented | Complete | `agents.md` |
| Decision log established | Complete | `decisions.md` |
| Local Git repository initialized | Complete | Repository on `main` with an initial documentation commit |
| Python/backend foundation | Complete | 6 tests pass; lint passes; health smoke reports five slots |
| Optimizer comparison | Complete | 20 focused tests; shared scenario API atomically persists GA/PSO/ACO metrics |
| Parking lifecycle API | Complete | 23 focused and 49 full tests pass; RFID lifecycle is atomic and retry-safe |
| Vision occupancy pipeline | Complete | 22 focused and 90 full tests pass; dynamic slots, ROI heuristic, smoothing, persistence, and JPEG API work |
| Prediction comparison | Complete | 116 focused prediction tests and 218 full tests pass; persisted comparisons and guarded runtime forecasts work without TensorFlow installed |
| Dashboard | Complete | Dynamic live slots, selected settings, forecast state, and both comparison tables are served at `/dashboard` without RFID rendering |
| Firmware integration | Software complete; physical validation pending | Both firmware targets compile, controller fail-closed/idempotent flow is implemented, and capture/recovery telemetry is privacy-safe; exact-board flash, wiring, local config, and bench results remain pending |
| End-to-end demo | Complete | Seeded history plus synthetic camera frames, lifecycle entry, allocation comparison, prediction, and dashboard APIs run through the documented simulator without hardware |
| Academic review dataset and experiments | Complete | 14-day privacy-safe dataset exported; LSTM, GRU, and Transformer trained and API-validated; 120-scenario optimizer benchmark and report generated |

## Academic Review Experiments (2026-10-14)

- Generated a five-slot, fourteen-day deterministic simulated dataset in
  `review_outputs/2026-10-15/dataset/review.db`, separate from application data.
- Exported 4,032 feature buckets, 27 model features, 6,274 privacy-safe raw
  records, ZIP, metadata, documentation, UTC timestamps, and SHA-256 hashes.
- Prepared 2,810 train, 592 validation, and 594 test sequences under the
  existing chronological 70/15/15, 12-step lookback contract.
- Trained and reloaded LSTM, GRU, and Transformer artifacts with TensorFlow
  2.22.0-rc0; validated content hashes and forecasts through the configured
  prediction API without fallback. Metrics are in
  `ml_results/model_comparison.csv`.
- Ran 120 optimizer scenarios with three seeds each. Every policy/reference
  had zero invalid assignments and rejected 60 full-capacity cases. Tables
  and figures are under `optimization_results/`.
- Generated `EXPERIMENTAL_REPORT.md` and `REPRODUCE.md`. The dataset ZIP was
  uploaded to Drive and shared read-only within `vit.ac.in`.
- Verification: 230 tests passed; Ruff passed. Two existing Starlette/AnyIO
  deprecation warnings remain. See ADR-013 for scope and limitations.

## Completed This Session

- Added a framework-free FastAPI dashboard route and static HTML/CSS/JavaScript
  assets. It renders every configured slot dynamically from parking-status data,
  shows selected optimizer/predictor settings, live occupancy, forecast target
  and fallback state, and persisted optimizer/predictor comparisons.
- Kept dashboard state privacy-safe: only selected settings are bootstrapped;
  dashboard assets do not render RFID or active-session identifiers, and the
  established prediction/comparison APIs remain unchanged.
- Added `scripts.run_simulated_demo`, which sends three deterministic synthetic
  JPEG frames to the existing camera API, enters a simulated vehicle, runs all
  optimizers on status-derived candidates, reads the prediction, and prints a
  RFID-free summary. Documented the seed/start/dashboard/demo sequence.
- Added focused route, API integration, dynamic-slot, fallback, demo HTTP
  sequence, multipart-camera, RFID-redaction, and installed-wheel static-asset
  coverage. Verified 5 focused tests and 223 full tests pass; 3 optional TensorFlow tests skip because
  TensorFlow is not installed. Ruff and `git diff --check` pass. The two
  FastAPI/Starlette warnings remain dependency deprecations.

- Added schema-v2 prediction manifests with the frozen non-RFID scaler
  contract, a privacy-safe feature-timeline `split_id`, and runtime validation
  before any model loading.
- Added atomic SQLite persistence of validated comparison manifests, the
  predictor benchmark API, and training-command persistence after a complete
  comparison.
- Added a shared, fixed-five-minute runtime input window plus a cached forecast
  service and `GET /api/prediction`. Unsafe, absent, stale, or invalid model
  artifacts degrade to a deterministic baseline without exposing RFID or
  filesystem details.
- Verified 116 focused prediction tests and 218 full tests. Three TensorFlow
  smoke tests skip because the optional dependency is not installed; Ruff and
  `git diff --check` pass. The two FastAPI/Starlette warnings remain
  dependency deprecations.

- Added transactionally replaceable deterministic prediction demo history with
  explicit ownership records, realistic five-minute context, completed
  sessions, allocation objectives, and no prediction-boundary RFID exposure.
- Added real optional TensorFlow/Keras builders for compact LSTM, GRU, and
  temporal Transformer regressors behind one `PreparedDataset`-only trainer.
- Added shared MAE, MSE, RMSE, and inference-latency evaluation plus
  content-addressed `.keras` files and atomically published compatibility
  manifests.
- Added seed and three-model training commands. GRU is the recommended
  affordable runtime candidate pending target-machine comparison results.
- Verified 119 focused prediction tests and 209 full tests. Three real
  TensorFlow smoke tests skip because the optional dependency is not installed;
  Ruff and `git diff --check` pass. The two FastAPI/Starlette warnings remain
  pre-existing dependency deprecations.

- Documented the shared prediction preprocessing contracts: persisted context,
  lifecycle, allocation, and optimizer records are aggregated into regular
  five-minute buckets with a twelve-bucket history and next-bucket target.
- Recorded privacy-preserving RFID aggregates, the chronological 70/15/15
  split, and training-only continuous-feature scaling to prevent leakage.
- Verified 72 focused prediction tests and 162 full tests; Ruff and
  `git diff --check` pass. The two warnings remain pre-existing dependency
  deprecations from the FastAPI/Starlette test-client integration.

- Removed fixed-five constraints from configuration, schemas, allocation,
  lifecycle, status, health, and SQLite persistence while keeping the committed
  five-slot demo configuration.
- Added data-preserving migrations for legacy slot IDs and context occupancy
  counts, including safe order-independent slot-name reseeding.
- Added configurable ROI models and deterministic JPEG edge-density detection
  with typed validation for empty, oversized, malformed, and out-of-bounds
  inputs.
- Added per-slot confidence filtering and temporal smoothing with atomic event
  persistence, active-session protection, rollback safety, and lifecycle-race
  reconciliation.
- Added `POST /api/camera/occupancy` with dynamic ordered results and complete
  hardware-independent multipart integration coverage.
- Verified 22 focused occupancy tests and 90 full tests; Ruff and
  `git diff --check` pass. The two warnings remain pre-existing dependency
  deprecations from FastAPI/Starlette test-client integration.

- Approved and documented a scalable occupancy-pipeline design: the demo keeps
  five slots while backend configuration, persistence, lifecycle, allocation,
  status, and vision operate on any non-empty configured slot set.
- Added ADR-011 to supersede the fixed-cardinality portion of ADR-008 and
  updated the architecture summary accordingly.
- Added the approved Milestone 4 test-driven implementation plan with five
  independently verifiable delivery tasks.

- Added production entry, exit, and parking-status contracts shared by hardware
  and simulated clients.
- Added database-backed entry/exit idempotency with one cross-operation key
  namespace and idempotent migration for existing SQLite databases.
- Added reserved lifecycle transactions that persist optimizer, session,
  allocation, and slot changes atomically and never allocate an occupied slot.
- Added integration coverage for retries, conflicts, full capacity, rollback,
  active status, and concurrent entries.
- Verified 23 focused lifecycle tests and 49 full tests; Ruff and
  `git diff --check` pass. The two test warnings are pre-existing deprecations
  from the FastAPI/Starlette test-client dependency stack.

- Added a normalized allocation request/result model and weighted objective
  shared by deterministic seeded GA, PSO, and ACO implementations.
- Enforced exactly five candidates and unconditional occupied-slot exclusion;
  full capacity raises a structured safe error.
- Added persisted optimizer runs plus `POST /api/allocation/run` and
  `GET /api/benchmarks/optimizers`.
- Incorporated code review fixes for nested API schemas, atomic benchmark
  persistence, genuinely bounded searches, deep immutability, typed stored-run
  responses, and structured full-capacity behavior.
- Verified 20 focused optimizer tests and 26 full tests; Ruff passes.

- Implemented the installable FastAPI backend foundation with typed environment
  and YAML configuration.
- Added all eight planned SQLite tables, transaction handling, and idempotent
  five-slot initialization.
- Added `/health`, isolated tests, developer commands, setup documentation, and
  ADR-007.
- Verified with `.venv/bin/python -m pytest` (6 passed),
  `.venv/bin/python -m ruff check .` (passed), `git diff --check` (passed), and a
  fresh TestClient health smoke response (`status=ok`, `slot_count=5`).

- Reviewed the supplied implementation design.
- Established architectural, agent, progress, and decision documentation.
- Added repository ignore rules for Python, ML, local configuration, databases, firmware builds, and editor files.
- Confirmed the GitHub plugin is already available.
- Installed the curated `jupyter-notebook` Codex skill for ML data exploration and model comparison work.
- Initialized the repository on the `main` branch and created the initial commit.
- Expanded `agents.md` with verified commit, safe push, and structured session-handoff procedures.

## Next Task

Configure local trusted-LAN firmware settings, grant operator USB serial
access, flash the confirmed boards, capture a real camera view, calibrate the
five ROIs, and run the isolated physical checklist. Review the academic report
against the institution's template.

## Blockers

Physical integration requires the listed hardware, local Wi-Fi credentials, camera placement, and measured ROI calibration. The professor's base paper template was not present in the repository.

## 2026-10-14 — Final review hardware and report deliverables

- Added PlatformIO firmware projects for an ESP32 DevKit controller and an AI-Thinker ESP32-CAM. Controller uses the existing entry/exit/status/health endpoints, NVS-backed idempotency, privacy-conscious serial messages, occupied-slot LEDs, OLED feedback, and confirmed-allocation-only servo movement. Both targets compiled successfully: controller 27,220 B RAM / 474,549 B flash; camera 49,628 B RAM / 836,777 B flash. Physical hardware was unavailable, so no flash/bench test is claimed.
- Added a bounded JPEG polling service for the existing occupancy API and an interactive real-camera ROI calibration tool that writes local `config/rois.json`; focused tests cover JPEG validation, API forwarding, ROI bounds/overlap, and real FastAPI occupancy processing.
- Added editable Graphviz system, wiring, circuit, and ML architecture diagrams with rendered SVG/PNG copies, a proposed pin map, BOM, power/safety notes, and physical validation instructions. The mapping remains a proposal, not a measured circuit.
- Generated an editable single-column DOCX and a 16-page A4 PDF from the existing measured dataset/model/optimizer results. Added demo procedure, software/physical test checklist, limitations, and submission checklist. The dataset/model Drive links are included and institution-restricted as previously documented.
- The institution's base paper template and physical boards were not available; no actual camera, RFID, gate, power, or microcontroller inference result is claimed. Review the report against the institutional template and complete the isolated bench checks when hardware is available.
- Final verification: `make test lint` passes (239 tests; two dependency deprecation warnings), `make firmware-controller firmware-camera` passes, and `make final-submission` generates the 16-page A4 PDF and editable DOCX. A copied-database live API smoke returned a finite GRU forecast with no fallback. Dataset CSV counts, timestamp ordering/uniqueness, no-UID export, ZIP CRC, SVG XML, and `git diff --check` also passed.

## 2026-10-20 — Completion audit and integration hardening

- Added `docs/FINAL_COMPLETION_AUDIT.md` with an evidence-based inventory and
  explicit software, compile-only, hardware-pending, and academic manual states.
- Hardened dashboard event privacy and request serialization; added direct SSE
  cursor/redaction coverage.
- Camera firmware now completes bounded JPEG writes and emits privacy-safe
  capture status, latency, byte-count, and heap events. ROI calibration rejects
  invalid timeouts and unbounded reads. Occupancy API response headers expose
  server processing time, which the poller can persist as timestamped JSONL.
- Added controller telemetry for RFID detection, API result/latency, Wi-Fi
  recovery, gate command delay, and heap; events contain no UIDs or secrets.
  Added CSV/JSON summarization and a repeatable supervised hardware procedure.
- Added editable monochrome block, wiring, and circuit diagrams, A4 PDF
  exports, a BOM, and firmware-to-pin-map validation. All 29 mappings match
  firmware headers; this is not physical validation.
- Rebuilt the formal monochrome A4 report with verified references and
  SHA-256-traceable evidence copies. Preserved the separate root clean PDF and
  the prior review report artifacts.
- A temporary-database demo exercised camera uploads, entry, allocation
  comparisons, prediction, and final occupancy without changing live data.
- Final verification: `make test` passes (257 tests; two dependency
  deprecation warnings), `make lint` passes, controller and camera firmware
  compile, `make final-submission` rebuilds the report, the 29-pin diagram
  validator passes, and `git diff --check` is clean. The isolated E2E run
  completed with three synthetic frames and a successful entry/allocation/
  forecast flow. Physical upload, serial capture, local Wi-Fi setup, ROI
  calibration, and power/actuation measurements remain pending.

## 2026-10-21 — Local workstation integration

- Configured ignored, mode-0600 controller and camera Wi-Fi settings from the
  active NetworkManager profile. The controller points to the current WLAN
  address on port 8001; no credentials are stored in tracked source.
- Added optional bearer authentication for `/api/*`. Started an enabled user
  systemd service bound only to the current WLAN address; `/health` is public,
  unauthorized API access returns 401, and an authorized status request returns
  200. The token is stored in a mode-0600 ignored environment file. The camera
  poller accepts this token through `SMART_PARKING_DEVICE_API_TOKEN`.
- Updated hardware setup and audit docs. The server and existing dashboard share
  the default SQLite file; the development server remains on loopback.
- Verification: 260 tests pass (two upstream deprecation warnings), Ruff passes,
  both configured firmware targets compile, report DOCX/PDF rebuild succeeds,
  29-pin diagram validation and `git diff --check` pass. Live API auth behavior
  returned health 200, unauthenticated API 401, authenticated API 200.
- The USB serial adapter is inaccessible to the current user (not in `uucp`);
  board identity is not confirmed. No firmware was flashed, and no RFID, servo,
  LED, camera, or power measurement is claimed. Update the service/controller
  address together if this Wi-Fi address changes.

## 2026-10-21 — First physical controller validation

- Read-only probing identified the attached controller as ESP32-D0WD-V3 revision
  3.1 with 4 MiB flash. Saved a private mode-0600 full-flash readback before
  writing the controller image. esptool verified hashes for the bootloader,
  partition table, and firmware; a second app image with RC522 diagnostics was
  also flashed and hash-verified. The backup is ignored by Git.
- Serial telemetry confirmed two controller boots and Wi-Fi connections. The
  protected server recorded successful health and authenticated parking-status
  requests from the ESP32 (8 of each after the diagnostic flash). Two boot heap
  observations and the failed RC522 check are captured in `output/hardware/`;
  the CSV/JSON summary marks unmeasured rates/timing as `NOT TESTED`.
- Added an `rfid_reader` boot event exposing the MFRC522 VersionReg value without
  logging card identifiers or credentials. It read `0xFF` before rewiring and `0x00` afterward (both `ready=false`); no
  card-read event reaches the server. The reader still does not answer SPI, so its
  physical power/reset/select/data connection remains unresolved; verify SDA/SS→GPIO13, SCK→18,
  MISO→19, MOSI→23, RST→4, 3.3 V and common ground before retesting.
- No camera health endpoint was found on the local /24. Camera, tag entry/exit,
  servo actuation, visual LED/OLED checks, and current draw remain unverified.
- `make test` passes (261 tests, two upstream deprecation warnings), Ruff passes,
  controller firmware compiles (46,776 B RAM / 846,569 B flash), and `git diff
  --check` is clean.

## 2026-10-21 — Follow-up user hardware report and estimates

- The user reports that the assembled tabletop hardware works after rewiring.
  This is recorded as a qualitative user report; no post-rewire serial capture,
  trial count, camera capture, or quantitative hardware result was provided.
- Updated the academic and experimental reports to distinguish that report from
  earlier pre-rewire RC522 probes and from measured evidence. Added a separate
  low-confidence engineering-estimate table for all hardware evaluation metrics,
  including assumed success/latency ranges, component timing/current estimates,
  historical measured free heap, and camera accuracy marked not estimable. None
  of the assumed ranges is presented as an observation or synthetic benchmark.
- Regenerated DOCX/PDF and the experimental report; `git diff --check` passes.
  Final verification after the estimate/report edits: 261 tests pass (two upstream
  deprecation warnings), Ruff passes, both firmware targets compile, the DOCX/PDF
  rebuild succeeds, and `git diff --check` is clean. The generated report does not
  change the remaining physical-validation requirements.

## 2026-10-24 — Controller Wi-Fi and RC522 diagnostics

- Reconfigured the ignored, mode-0600 local ESP32 credentials to the active
  workstation Wi-Fi and updated the controller API address. Flashed the
  controller; PlatformIO verified the firmware image hash. The ESP32 associated
  with Wi-Fi and the authenticated hardware API logged repeated status `200`
  responses. The dashboard continues to use the shared local SQLite state.
- Added a boot diagnostic that compares the MFRC522 library read with a direct
  250 kHz SPI version-register read, and reports reset and idle-MISO levels.
  The live board reports `VersionReg=0x00` at both speeds, reset high, and
  MISO high while idle. The reader's power LED is lit in the supplied photo.
- The user confirms the pin mapping is correct. No RFID UID was read and no
  gate actuation was attempted; the gate remains closed. This evidence points
  to a nonresponsive reader or SPI signal path, but does not distinguish a
  defective RC522 from select/clock/data continuity at the module.
- `make test` passes (261 tests, two upstream deprecation warnings), Ruff
  passes, and the controller firmware compiles. A private 4 MiB pre-diagnostic
  flash backup remains ignored by Git with mode 0600.
