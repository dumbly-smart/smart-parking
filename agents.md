# Repository Guide for Agents

## Mission

Build the smart parking system described in `2026-09-03-smart-parking-design.md` and summarized in `architecture.md`. Keep it runnable without hardware while preserving a clean path to the ESP32-CAM and ESP32 DevKit prototype.

## Source-of-Truth Order

When documents differ, use this order:

1. The user's current instruction.
2. Accepted entries in `decisions.md`.
3. `2026-09-03-smart-parking-design.md` for product scope and requirements.
4. `architecture.md` for component boundaries and data flow.
5. `progress.md` for current execution state.

Do not silently resolve contradictions. Record a decision or ask for clarification when the higher-priority source does not settle the issue.

## Working Rules

- Read the four project documents before planning a material change.
- Keep `progress.md` current whenever a milestone starts, completes, or becomes blocked.
- Add an entry to `decisions.md` for choices that affect public interfaces, dependencies, data models, hardware pins, algorithms, or repository structure.
- Prefer the smallest implementation that completes a vertical slice in demo mode.
- Keep hardware access behind interfaces so unit and integration tests do not require devices.
- Never commit secrets, Wi-Fi credentials, calibrated private configuration, model datasets, generated artifacts, or the SQLite runtime database.
- Do not change optimizer weights, slot count, endpoint contracts, or evaluation metrics without recording the decision.
- Preserve deterministic seeds in tests and benchmark fixtures.

## Implementation Order

1. Repository and Python project scaffolding.
2. Domain models, configuration, SQLite initialization, and five-slot seed data.
3. Shared allocation cost interface plus GA, PSO, and ACO comparison.
4. Entry/exit and parking-status API flows in demo mode.
5. Occupancy heuristic, ROI configuration, and camera update flow.
6. Shared prediction preprocessing, deterministic fallback, and model comparison scripts.
7. Dashboard and complete simulated lifecycle.
8. ESP32-CAM and controller firmware integration.
9. CNN and trained sequence-model artifacts after datasets exist.

Each stage should leave a runnable, tested state. Avoid scaffolding later stages before the interfaces they depend on are established.

## Expected Engineering Practices

- Use Python type hints and explicit request/response schemas.
- Keep domain logic outside FastAPI route handlers.
- Use migrations or idempotent initialization for schema changes.
- Test safety invariants, fallback paths, and persistence side effects.
- Compare algorithms on identical seeded inputs.
- Treat timestamps as timezone-aware UTC in storage and convert only for presentation.
- Return structured errors suitable for both firmware and dashboard clients.
- Document firmware pin assignments before committing sketches.

## Verification Baseline

Until project tooling is created, documentation changes must pass whitespace checks and internal-link/path review. Once the Python project exists, every change should run the relevant focused tests plus the full configured test and lint commands. Firmware changes must compile for their target board and include reproducible build instructions.

## Progress Handoff

Before ending a work session, update `progress.md` with:

- what changed,
- what was verified,
- the next concrete task,
- any blocker or unresolved decision.

Keep entries factual and concise; Git remains the detailed history.
