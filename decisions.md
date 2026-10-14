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

## ADR-008: Discrete seeded optimizer contract

- Date: 2026-09-03
- Status: Accepted

### Context

GA, PSO, and ACO must be comparable on a five-slot discrete allocation problem
without allowing algorithm-specific objectives or occupancy handling.

### Decision

Represent every run as one validated five-candidate `AllocationRequest` and
return one `AllocationResult`. Filter occupied candidates before any search,
evaluate all candidates through the shared weighted objective, use a local RNG
seed, cap iterations at 10,000, and benchmark the same immutable request across
all algorithms.

### Consequences

Semantic results are reproducible while runtime remains a measured value.
Malformed scenarios fail validation and full capacity produces a structured
409 response. Algorithm implementations may evolve independently only behind
this contract.

## ADR-009: Persistent lifecycle idempotency and reserved transactions

- Date: 2026-09-04
- Status: Accepted

### Context

RFID clients can retry after network timeouts, concurrent entries can observe
the same free-slot state, and a gate command must never describe a lifecycle
change that failed to persist.

### Decision

Require every entry and exit request to carry an idempotency key. Entry and exit
keys share one database-backed namespace and identify one operation type and
RFID UID across server restarts. Reserve SQLite lifecycle writes with
`BEGIN IMMEDIATE`, persist all related state in one transaction, and return a
successful open-gate response only after commit.

### Consequences

Identical retries replay their original stored response without duplicate
sessions or allocations. Conflicting key reuse has a stable HTTP 409 response,
and concurrent entries cannot allocate from the same stale snapshot. Clients
must generate and retain distinct keys for each intended entry and exit.

## ADR-010: Immutable lifecycle replay snapshots and unsigned seeds

- Date: 2026-09-04
- Status: Accepted

### Context

Idempotent replies must remain stable when configured slot names change.
Lifecycle seed derivation also uses the unsigned first eight bytes of a SHA-256
digest, which can exceed SQLite's signed 64-bit integer range.

### Decision

Store the entry-time and exit-time slot names on each parking session and use
those snapshots for replay responses. Store optimizer seeds as hexadecimal text
while exposing them as integers through typed Python and HTTP contracts. Bound
lifecycle scenario identifiers to `entry:` followed by the SHA-256 hex digest
of the idempotency key.

### Consequences

Configuration changes do not alter prior successful responses, all unsigned
64-bit seeds round-trip without precision loss, and maximum-length valid keys
cannot overflow the optimizer scenario contract. Existing integer seed rows
remain readable.

## ADR-011: Configuration-driven slot cardinality

- Date: 2026-09-04
- Status: Accepted

### Context

The physical prototype currently has five parking slots, but fixed five-slot
validation in configuration, persistence, API schemas, and optimizer contracts
would require source changes for every larger or smaller deployment. The vision
pipeline must return all configured slot observations rather than a hard-coded
five-element result.

### Decision

Treat five slots as the committed demo and hardware configuration, not a
software invariant. Accept any non-empty collection of uniquely identified
positive slot IDs, require ROI mappings to match that configured set exactly,
and make persistence, lifecycle, allocation, status, and vision contracts
cardinality-independent. Preserve deterministic optimizer comparison on the
same candidate set for every algorithm.

This decision supersedes the fixed five-candidate portion of ADR-008. Its
remaining optimizer-contract requirements stay accepted.

### Consequences

Deployments can change slot count through configuration while the current demo
continues to use five slots. The legacy SQLite slot-ID constraint requires an
idempotent data-preserving migration. Firmware remains limited by its configured
physical outputs until its own integration milestone.

## ADR-012: Runtime prediction uses schema-v2 frozen scaler contracts

- Date: 2026-09-11
- Status: Accepted

### Context

A trained Keras model must receive inputs transformed with the scaler fitted
from its training partition. Recomputing a scaler at runtime would silently
change model input semantics. The prior artifact schema carried geometry and
feature names but not the immutable scaler, while its split identifier did not
distinguish changed aggregate feature values.

### Decision

Publish schema-v2 prediction manifests containing the existing immutable
continuous-feature scaler metadata and include the canonical privacy-safe
feature timeline in `PreparedDataset.split_id`. Persist only validated,
whitelisted manifest summaries. Runtime validates this full contract and the
artifact digest before lazy model loading; schema-v1 manifests remain visible
as historical comparison records but are not eligible for runtime inference.

### Consequences

Runtime forecasts cannot accidentally use a changed source snapshot or scaler.
No raw source rows or RFID identifiers are stored in the manifest or exposed
through APIs. Older artifacts safely degrade to the deterministic baseline
until retrained under schema v2.

## ADR-013: Reproducible academic review experiments use isolated synthetic data

- Date: 2026-10-14
- Status: Accepted

### Context

The final project review needs portable dataset exports, genuine model
comparison results, and controlled optimizer measurements without replacing
the working application database or presenting simulated observations as real
measurements.

### Decision

Generate the review corpus in a dedicated dated SQLite database using the
existing demo-data and feature-timeline implementations. Make sampled
occupancy agree with active sessions and slot state, and persist all four
configured allocation objective components. Export only privacy-safe source
observations and the shared chronological feature timeline. Use the existing
prepared prediction split for all model families. Compare allocation
heuristics on identical seeded scenarios against first-available and
exhaustive-search references, recording full-capacity rejections separately.

### Consequences

Review outputs are reproducible and isolated from application records. Their
metrics describe synthetic scenarios and server execution only; they do not
claim measured site performance, physical throughput, or microcontroller
inference. Negative finite scaler means are valid because centered continuous
features can have signed training averages; scaler values still must be finite
and scales must remain positive.
