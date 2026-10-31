# Architecture decisions

## ADR-001: Host/server coordination

The local Python service owns persistence, parking-session validation, allocation and forecasting. The ESP32 controller handles RFID polling, local feedback and the supervised demo servo. This keeps the device workflow bounded and allows the software demo to run without hardware.

## ADR-002: RFID sessions define occupied state

A slot becomes occupied when a valid RFID entry, allocation and session commit together. A confirmed exit closes the active session and frees its assigned slot. The dashboard and LEDs consume the same server status so there is one occupancy source of truth.

## ADR-003: Atomic idempotent lifecycle

Every entry and exit carries a persisted idempotency key. Database transactions prevent duplicate sessions, duplicate slot assignment and inconsistent exit state. The controller preserves the pending key across retries and fails closed when authorization cannot be confirmed.

## ADR-004: Shared allocation objective

All policies use the configured objective: `C(s) = 0.35D(s) + 0.30G(s) + 0.20W(s) + 0.15F(s)`. Occupied slots are infeasible. First available, exact enumeration, GA, PSO and ACO use identical candidates and seeded scenarios.

## ADR-005: Server-side forecasting

LSTM, GRU and temporal Transformer inference remains on the server. All models share a chronological 70/15/15 split, 12-step input window, 27 features and training-only normalization. The continuous occupancy target is evaluated with regression metrics and a persistence baseline.

## ADR-006: Controller pin and power contract

The active pin map is defined in `firmware/esp32_controller/include/pins.h` and copied into `docs/hardware/pin_connections.csv`. RC522 and OLED logic use 3.3 V. Each LED has its own series resistor. The tabletop servo uses a separate regulated supply and common ground; it is not a vehicle barrier.

## ADR-007: Monochrome report and traceable evidence

The report is generated from repository sources, stored synthetic experiment outputs and timestamped controller logs. It distinguishes software results, synthetic data and physical observations. Unmeasured results remain `NOT TESTED`; estimates are not presented as measurements.
