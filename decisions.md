# Smart Parking Architecture Decision Log

This file records project-level decisions. New entries are append-only; supersede an older decision with a new entry instead of rewriting history.

## Decision template

```markdown
## ADR-NNN: Short title

- Date: YYYY-MM-DD
- Status: Proposed | Accepted | Superseded by ADR-NNN

### Context

Why a decision is needed.

### Decision

What the project will do.

### Consequences

Important benefits, costs, and constraints.
```

## ADR-001: Server-centered architecture

- Date: 2026-09-03
- Status: Accepted

### Context

The embedded devices have limited compute and storage, while the project requires vision, time-series models, optimization benchmarks, persistence, APIs, and a dashboard.

### Decision

Run computation and persistence on a Python laptop/server. Limit the ESP32-CAM to image delivery and the ESP32 DevKit to RFID input, display, indicators, and gate control.

### Consequences

The implementation is easier to test and evolve, but live hardware operation depends on reliable local Wi-Fi and backend availability. The gate must therefore fail closed.

## ADR-002: Fixed-ROI occupancy detection for version 1

- Date: 2026-09-03
- Status: Accepted

### Context

The prototype has exactly five slots and a fixed camera, so general-purpose object detection adds training and runtime complexity without being required for the first demonstration.

### Decision

Detect occupancy independently within five configured Regions of Interest. Provide a heuristic baseline and an optional small Keras CNN using the same output interface.

### Consequences

The camera must remain fixed and ROI calibration is required per installation. The system stays runnable without a trained model.

## ADR-003: Shared interfaces for fair algorithm comparison

- Date: 2026-09-03
- Status: Accepted

### Context

The project must compare three allocation algorithms and three prediction models. Comparisons are invalid if inputs, splits, objectives, or metrics differ.

### Decision

GA, PSO, and ACO will use one normalized cost interface and identical seeded scenarios. LSTM, GRU, and temporal Transformer models will use identical preprocessing and train/validation/test splits.

### Consequences

Algorithm-specific tuning remains possible, but benchmark inputs and required outputs cannot diverge. Results will include quality metrics and execution/inference latency.

## ADR-004: Configurable multi-objective allocation cost

- Date: 2026-09-03
- Status: Accepted

### Context

Slot selection must optimize walking distance, congestion, waiting-time contribution, and fairness simultaneously.

### Decision

Use normalized objectives with default weights of 0.35 distance, 0.30 congestion, 0.20 waiting, and 0.15 fairness. Store weights in configuration and require them to sum to 1.0.

### Consequences

All optimizers can be compared through one scalar objective while retaining an objective breakdown. Changing policy does not require algorithm code changes.

## ADR-005: SQLite and a framework-free dashboard for version 1

- Date: 2026-09-03
- Status: Accepted

### Context

The prototype is a single-server, five-slot system and must be easy to run during demonstrations.

### Decision

Use SQLite for persistence and serve plain HTML, CSS, and JavaScript from FastAPI for the dashboard.

### Consequences

Deployment has few moving parts. Multi-server scaling and advanced frontend state management are intentionally deferred.

## ADR-006: Hardware-independent demo mode is mandatory

- Date: 2026-09-03
- Status: Accepted

### Context

Software development, tests, and demonstrations cannot depend on continuous access to the physical parking rig.

### Decision

Support seeded context/occupancy data, simulated camera updates, simulated RFID entry, deterministic prediction fallback, and optimizer comparison without hardware. Enable hardware integrations only through configuration.

### Consequences

Hardware boundaries must be replaceable adapters rather than embedded in domain logic. The simulated lifecycle becomes the primary integration-test path.

## ADR-007: Typed configuration and standard-library SQLite boundary

- Date: 2026-09-03
- Status: Accepted

### Context

The backend needs strict startup validation, idempotent schema initialization,
and a dependency footprint suitable for a five-slot single-process prototype.

### Decision

Use Pydantic Settings for environment configuration, validated YAML for parking
policy and slot metadata, and a small standard-library `sqlite3` persistence
boundary. Schema initialization uses idempotent DDL and configured slot upserts.
Version 1 accepts only `sqlite:///` database URLs.

### Consequences

Invalid slot counts, weights, or unsafe hardware-mode combinations fail at
startup. SQL transactions remain explicit and testable without an ORM, while a
future persistence replacement must preserve the service-facing database
boundary and migration semantics.
