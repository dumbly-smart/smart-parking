# Repository Guide for Agents

## Mission

Maintain the current RFID-based smart parking system: FastAPI and SQLite backend, ESP32 controller, five slot LEDs, OLED, supervised demonstration servo, 3D dashboard, prediction models, and allocation comparisons. Parking occupancy is derived from committed RFID vehicle sessions.

## Source-of-Truth Order

1. The user's current instruction.
2. Accepted entries in `decisions.md`.
3. `architecture.md` for current system boundaries.
4. `progress.md` for milestone status.

## Working Rules

- Keep the app runnable without physical hardware.
- Keep hardware access behind clear interfaces.
- Never commit secrets, Wi-Fi credentials, private configuration, or runtime databases.
- Preserve deterministic seeds in the demo and optimizer benchmarks.
- Record changes to public APIs, dependencies, data models, pins, and algorithms in `decisions.md`.

## Implementation Areas

1. Domain models, configuration, SQLite initialization, and slot data.
2. Idempotent RFID entry/exit and parking status.
3. Shared allocation objective and NSGA-II, GA, PSO, ACO comparisons.
4. Shared prediction preprocessing, deterministic fallback, and model comparison.
5. Dashboard and simulated lifecycle.
6. ESP32 controller integration and hardware evaluation.

## Engineering Practices

- Use explicit request/response schemas and keep domain logic outside routes.
- Preserve atomic session handling and safe failure behavior.
- Compare algorithms on identical seeded inputs.
- Treat timestamps as timezone-aware UTC.
- Document firmware pins and electrical constraints.
- Update `progress.md` when milestones change.
