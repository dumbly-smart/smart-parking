# Parking Lifecycle API Design

## Scope

Milestone 3 adds the production vehicle lifecycle to the FastAPI backend. RFID
clients can enter, safely retry an entry, exit, safely retry an exit, and read
the current five-slot state. The same contracts support both hardware and
simulated clients; runtime mode does not alter domain behavior.

This milestone does not add camera occupancy updates, prediction, dashboard
views, or firmware integration.

## Architecture

The feature has four focused boundaries:

- `backend/app/models/parking.py` defines immutable request, response, status,
  and domain-error models shared by services, routes, and tests.
- `backend/app/services/parking.py` owns entry and exit policy, converts
  persisted slot state into optimizer candidates, and invokes the configured
  optimizer.
- `backend/app/db.py` owns atomic SQLite entry and exit transactions and all
  lifecycle persistence.
- `backend/app/routes/parking.py` exposes HTTP endpoints and translates typed
  domain conflicts into structured HTTP responses.

Route handlers contain no lifecycle policy. The database methods form the
transaction boundary. Entry uses `BEGIN IMMEDIATE` so concurrent requests
cannot allocate from the same stale free-slot snapshot.

## API Contracts

### Vehicle entry

`POST /api/vehicle/entry` accepts:

```json
{
  "rfid_uid": "04-A1-B2-C3",
  "idempotency_key": "entry-0001"
}
```

Both fields are required, trimmed, and non-empty. RFID UIDs are normalized to
uppercase. The idempotency key identifies one requested operation rather than
a vehicle or its complete parking lifetime.

A successful response contains the parking session ID, normalized RFID UID,
assigned slot ID and name, optimizer name, allocation cost, timezone-aware UTC
entry timestamp, and `gate_action: "open"`.

Repeating the same request with the same key returns the original stored result
without creating another vehicle, session, allocation, or optimizer run. A new
entry operation for a vehicle with an active session is rejected.

### Vehicle exit

`POST /api/vehicle/exit` accepts the same two required identifiers. A
successful response contains the closed session ID, normalized RFID UID,
released slot ID and name, timezone-aware UTC exit timestamp, and
`gate_action: "open"`.

Repeating the same exit request with the same key returns the original stored
result without updating the session again. A vehicle without an active session
is rejected.

### Parking status

`GET /api/parking/status` returns exactly five slots ordered by slot ID. Each
item contains slot ID, name, normalized walking distance, zone, occupied state,
last-update timestamp, and nullable active session ID and RFID UID.

## Entry Data Flow

1. Validate and normalize the request.
2. Start a SQLite `BEGIN IMMEDIATE` transaction.
3. Look up the idempotency key across entry and exit operations. Replay an
   identical request or reject conflicting use.
4. Upsert the RFID UID in `vehicles` and reject a new entry operation if that
   vehicle already has an active session.
5. Read all five slots and derive one optimizer candidate per slot:
   - `distance` is the configured normalized walking distance;
   - `congestion` is the occupied fraction among slots in the same zone;
   - `waiting` is `0.0` until the waiting-time source is introduced;
   - `fairness` is `0.0` until allocation history feeds the fairness policy.
6. Invoke the optimizer selected by `Settings.selected_optimizer` using the
   configured objective weights. Derive its deterministic integer seed from
   the first eight bytes of SHA-256 over the normalized RFID UID, a colon, and
   the idempotency key, interpreted as an unsigned value. Use `entry:` plus the
   SHA-256 hex digest of the idempotency key as the bounded scenario ID.
7. Persist the optimizer run, parking session, allocation, and occupied slot
   update in the same transaction.
8. Commit before returning the successful response.

If every slot is occupied, allocation fails and the transaction rolls back.

## Exit Data Flow

1. Validate and normalize the request.
2. Start a SQLite `BEGIN IMMEDIATE` transaction.
3. Look up the key across entry and exit operations. Replay an identical exit
   or reject conflicting use.
4. Locate the vehicle's active session; reject the request if none exists.
5. Set the session exit timestamp and exit key, then mark its slot free.
6. Commit before returning the successful response.

SQLite initialization adds a nullable `exit_idempotency_key` column to
`parking_sessions`, entry-time and exit-time slot-name snapshots, and a unique
partial index for populated exit keys. Optimizer seeds use hexadecimal text in
SQLite so unsigned 64-bit values round-trip exactly. Initialization detects and
migrates existing version-1 databases idempotently.

## Idempotency Rules

Entry and exit keys share one logical namespace. A key identifies exactly one
operation type and RFID UID.

- Same key, operation, and RFID UID: replay the original response.
- Same key with a different RFID UID: return `409 idempotency_conflict`.
- Entry key reused for exit, or exit key reused for entry: return
  `409 idempotency_conflict`.
- New entry key for an actively parked vehicle: return
  `409 vehicle_already_parked`.

Persisted database state is the source for replay responses, so idempotency
survives server restarts and works identically for hardware and simulated
clients.

## Error Handling

Expected domain conflicts use HTTP 409 and the established structured shape:

```json
{
  "detail": {
    "code": "no_available_slot",
    "message": "no parking slot is available"
  }
}
```

Stable conflict codes are:

- `no_available_slot` when all five slots are occupied;
- `vehicle_already_parked` for a new entry on an active vehicle;
- `vehicle_not_parked` when exit has no active session; and
- `idempotency_conflict` for conflicting key reuse.

FastAPI validation failures remain HTTP 422. Unexpected optimizer or
persistence failures roll back the transaction and return no gate action.

## Safety and Atomicity

The occupancy snapshot used for selection and the final slot update occur in
one reserved write transaction. Database uniqueness constraints are the final
defense against multiple active sessions for one vehicle or slot. The service
always gives the optimizer exactly five candidates and never bypasses its
occupied-slot exclusion.

An entry or exit response is constructed from committed state and returned only
after commit. A failed request therefore cannot instruct a controller to open
the gate.

## Testing

Development follows red-green-refactor. Integration tests use temporary SQLite
databases with the real FastAPI application, parking service, optimizers, and
persistence layer.

Coverage includes:

- request normalization and rejection of blank identifiers;
- idempotent migration of fresh and existing databases;
- entry selects a free slot and atomically persists one vehicle, active
  session, allocation, optimizer run, and occupied-slot update;
- identical entry retry returns the original result without duplicate rows;
- a new entry key for an active vehicle returns `vehicle_already_parked`;
- exit closes the active session and frees its slot;
- identical exit retry returns the original result without another update;
- exit for a vehicle without an active session returns `vehicle_not_parked`;
- cross-operation and cross-vehicle key reuse returns
  `idempotency_conflict`;
- full capacity returns `no_available_slot` without partial writes;
- pre-occupied slots are never selected;
- concurrent entry transactions cannot assign the same slot;
- valid idempotency keys through 128 characters produce bounded scenario IDs;
- unsigned lifecycle seeds round-trip through persistence and the API;
- entry and exit replay payloads survive slot-name configuration changes;
- parking status returns five correctly ordered slots with active-session
  details; and
- an injected persistence failure rolls back the complete lifecycle change.

The focused tests, complete test suite, Ruff, and `git diff --check` must pass
before the milestone is marked complete.

## Documentation and Project State

The README gains request and response examples for the three endpoints.
`decisions.md` records the persistent idempotency namespace and reserved
transaction boundary. `progress.md` records Milestone 3 evidence and identifies
the vision occupancy pipeline as the next task after completion.
