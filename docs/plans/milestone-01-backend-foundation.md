# Milestone 1: Backend Foundation Plan

## Goal

Deliver an installable, typed FastAPI service that initializes SQLite
idempotently, seeds exactly five configured slots, and reports health without
requiring hardware.

## Public interfaces first

- `backend.app.config.Settings` loads environment overrides and validates a
  five-slot YAML configuration whose allocation weights sum to one.
- `backend.app.db.Database` exposes idempotent `initialize()` and connection
  helpers while keeping SQL out of route handlers.
- `backend.app.main.create_app(settings=None)` is the testable application
  factory; `app` is the ASGI entry point.
- `GET /health` returns `status`, `mode`, `database`, and `slot_count`.
- Developer commands are `make install`, `make test`, `make lint`, and
  `make run`.

## TDD and implementation sequence

1. Add configuration, database, and health contract tests; run them to confirm
   failure because the application modules do not exist.
2. Add dependency manifests, package structure, default configuration, and
   environment example.
3. Implement typed settings and strict five-slot/weight validation.
4. Implement the eight planned SQLite tables with foreign keys, constraints,
   indexes, UTC timestamp defaults, and an idempotent five-slot upsert.
5. Implement lifespan initialization and the health route.
6. Run focused tests, the full suite, lint, and an application smoke test.
7. Review input/configuration failure behavior, documentation, and the complete
   diff; then commit only the milestone files.

## Exit criteria

- Repeated initialization produces exactly five configured slots and all eight
  planned tables.
- Invalid slot counts or objective weights fail during startup/config loading.
- `/health` reports a usable database and five slots.
- A fresh developer can install, test, lint, and run the service using the
  documented commands.
