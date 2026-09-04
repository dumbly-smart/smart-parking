# Smart Parking Project Progress

Last updated: 2026-09-04

## Current Status

Milestone 4 (scalable vision occupancy pipeline) is complete and verified on
`main`; implementation changes run through commit `88275f0`.

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
| Prediction comparison | Not started | Shared split evaluates LSTM, GRU, and Transformer with required metrics |
| Dashboard | Not started | Live five-slot state and both comparison tables are visible |
| Firmware integration | Not started | Both sketches build and complete the documented hardware flow |
| End-to-end demo | Not started | Seed, simulated camera, RFID entry, allocation, prediction, and UI run without hardware |

## Completed This Session

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

Begin the prediction comparison milestone with shared preprocessing and one
deterministic train/validation/test split for every predictor.

## Blockers

None for backend development. Physical integration will later require the final pin map, local Wi-Fi credentials, camera placement, calibrated ROI coordinates, and access to the listed hardware.
