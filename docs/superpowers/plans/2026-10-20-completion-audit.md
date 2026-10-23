# Smart Parking Completion Audit Plan

> **For agentic workers:** Use the current project task instructions; this plan is executed inline and does not require an approval gate.

**Goal:** Close verifiable software, firmware, diagram, evaluation, and academic-deliverable gaps without claiming unperformed physical tests.

**Architecture:** Preserve the FastAPI/SQLite, ESP32 controller, ESP32-CAM, ROI heuristic, existing ML/optimizer experiments, and dashboard boundaries. Add focused fixes and evidence artifacts, leaving physical validation clearly marked as pending when the attached board cannot be accessed.

**Tech Stack:** Python, FastAPI, SQLite, pytest, Ruff, PlatformIO, Arduino C++, Graphviz, DOCX/PDF tooling.

**Spec:** User's Smart Parking Project Completion Prompt (2026-10-20).

## Global Constraints

- Never commit credentials, calibrated private configuration, local databases, or runtime artifacts.
- Preserve synthetic-versus-measured provenance; never fabricate hardware metrics or citations.
- Preserve the existing manually reviewed PDF; build revised report outputs separately.
- Keep the gate fail-closed and the servo demo-only with separate regulated power and common ground.

## Review Focus

- RFID retries, restart recovery, invalid server replies, and event idempotency — controller/API integration tests and firmware compile.
- Camera invalid/offline/conflicting frames — occupancy and camera-ingest tests.
- Stable slot IDs and configurable geometry — dashboard tests.
- Diagram GPIO labels and hardware metrics provenance — validator and evaluation harness.
- Report claims, references, monochrome output, and generated-vs-authoritative file paths — report rebuild and checklist.

## Tasks

1. Audit existing documentation, source, tests, benchmark outputs, and hardware status; write `docs/FINAL_COMPLETION_AUDIT.md`.
2. Fix hardware event/dashboard regressions and add integration coverage for ordered, privacy-safe event delivery.
3. Harden camera capture, ingestion, ROI handling, and occupancy reconciliation with focused tests.
4. Validate controller and camera firmware builds; create a serial measurement logger and mark unmeasured instruments as `NOT TESTED`.
5. Generate validated monochrome diagrams, pin table, BOM, and electrical safety instructions from firmware pin definitions.
6. Verify stored ML/optimizer outputs and rebuild an academic DOCX/PDF into a new output directory without overwriting the reviewed PDF.
7. Update architecture/decisions/progress/checklist, then run `make test`, `make lint`, both firmware targets, `make final-submission`, diagram validation, and `git diff --check`.
