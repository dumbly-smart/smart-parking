# Demo Entry/Exit API Design

## Scope

Milestone 3 adds the hardware-independent parking lifecycle to the FastAPI
backend. A simulated RFID client can enter, retry an entry safely, exit, retry
an exit safely, and inspect the current five-slot state. The implementation
uses the configured optimizer and the existing SQLite tables while preserving
the invariant that an occupied slot is never assigned.

This milestone does not add camera occupancy updates, prediction, dashboard
views, or firmware integration.

## Architecture

The feature is divided into four focused areas:

- `backend/app/models/parking.py` defines immutable request, response, status,
  and domain-error models shared by the service, routes, and tests.
- `backend/app/services/parking.py` owns entry/exit behavior, derives optimizer
  candidates from persisted state, selects the configured optimizer, and maps
  persistence outcomes to domain errors.
- `backend/app/db.py` owns atomic SQLite entry and exit transactions, including
  idempotency checks and all related persistence changes.
- `backend/app/routes/parking.py` exposes the HTTP endpoints and translates
  domain errors into structured API conflicts.

Route handlers contain no parking lifecycle rules. The service-facing database
methods form the transaction boundary; entry uses `BEGIN IMMEDIATE` so two
requests cannot both allocate the same free slot from stale reads.

## API Contracts

### Vehicle entry

`POST /api/vehicle/entry`

Request:

```json
{
  "rfid_uid": "04-A1-B2-C3",
  "idempotency_key": "entry-0001"
}
```

Both strings are required, trimmed, and non-empty. The idempotency key
identifies this entry operation, not the vehicle or its lifetime.

A successful response contains:

- the parking session ID;
- the normalized RFID UID;
- assigned slot ID and name;
- configured optimizer name;
- allocation cost;
- the session entry timestamp; and
- `gate_action: "open"`.

Repeating the same entry request with the same key returns the stored successful
result without creating another vehicle, session, allocation, or optimizer run.
A new entry key for a vehicle that already has an active session is rejected.

### Vehicle exit

`POST /api/vehicle/exit`

The request contains the same two required identifiers. A successful response
contains the closed session ID, normalized RFID UID, released slot ID and name,
exit timestamp, and `gate_action: "open"`.

Repeating the same exit request with the same key returns the stored successful
result without updating the session again. A vehicle without an active session
is rejected.

### Parking status

`GET /api/parking/status`

The response always contains exactly five slots ordered by slot ID. Each item
contains slot ID, name, walking distance, zone, occupied state, update timestamp,
and nullable active session ID and RFID UID.

## Entry Data Flow

1. Validate the request and normalize its strings.
2. Start a SQLite `BEGIN IMMEDIATE` transaction.
3. Look up the idempotency key. Return the original response for an identical
   retry, or reject use of the key for different request data or an exit.
4. Upsert the RFID UID in `vehicles` and reject a new entry operation when that
   vehicle already has an active session.
5. Read all five slots and derive one optimizer candidate per slot:
   - `distance` is the configured normalized walking distance;
   - `congestion` is the occupied fraction among slots in the candidate's zone;
   - `waiting` is `0.0` until a waiting-time data source is introduced;
   - `fairness` is `0.0` until a fairness-history data source is introduced.
6. Run the optimizer selected by `Settings.selected_optimizer` with the
   configured objective weights and a deterministic request seed.
7. Persist its optimizer run, parking session, allocation, and occupied slot
   update in the same transaction.
8. Commit and return the successful response.

If every slot is occupied, the optimizer rejects the request and all database
work rolls back.

## Exit Data Flow

1. Validate and normalize the request.
2. Start a SQLite `BEGIN IMMEDIATE` transaction.
3. Look up the exit idempotency key. Return the original response for an
   identical retry, or reject conflicting use.
4. Locate the vehicle's active session; reject the request if none exists.
5. Set the session exit timestamp and exit key, then mark its slot free.
6. Commit and return the successful response.

The schema gains a nullable `exit_idempotency_key` on `parking_sessions` and a
unique partial index for populated keys. Database initialization detects and
adds the column when opening an existing version-1 database, then creates the
index idempotently.

## Idempotency Rules

Entry and exit keys share one logical namespace. A key can identify exactly one
operation, operation type, and RFID UID.

- Same key, operation, and RFID UID: replay the original response.
- Same key with a different RFID UID: `409 idempotency_conflict`.
- Entry key reused for exit, or exit key reused for entry:
  `409 idempotency_conflict`.
- New entry key for an actively parked vehicle:
  `409 vehicle_already_parked`.

Stored database state, rather than an in-memory cache, is the source for replay
responses, so retries remain safe across process restarts.

## Error Handling

Expected domain conflicts use HTTP 409 and the existing structured detail
shape:

```json
{
  "detail": {
    "code": "no_available_slot",
    "message": "no parking slot is available"
  }
}
```

Defined codes are:

- `no_available_slot` when all five slots are occupied;
- `vehicle_already_parked` for a new entry operation on an active vehicle;
- `vehicle_not_parked` when exit has no active session; and
- `idempotency_conflict` for key reuse with different request identity or type.

Pydantic/FastAPI validation failures remain HTTP 422. Unexpected optimizer or
persistence failures return no gate command and roll back the complete
transaction.

## Safety and Atomicity

Occupied state used for selection and the final occupied-slot update occur
inside one reserved SQLite write transaction. Database uniqueness constraints
remain the final defense against multiple active sessions for one vehicle or
slot. The service never constructs an optimizer request with fewer than five
candidates and never overrides the optimizer's occupied-slot exclusion.

The entry response is produced only after the transaction commits. A failed
request therefore cannot instruct the controller to open the gate.

## Testing

Development follows red-green-refactor. Integration tests use a temporary
SQLite database and the real FastAPI application, service, optimizers, and
persistence layer.

Coverage includes:

- entry returns a free slot and persists exactly one vehicle, active session,
  allocation, optimizer run, and occupied-slot update;
- identical entry retry returns the original response without duplicate rows;
- entry with a new key for an active vehicle returns
  `vehicle_already_parked`;
- exit closes the active session and frees its slot;
- identical exit retry returns the original response without another update;
- exit for a vehicle without an active session returns `vehicle_not_parked`;
- cross-operation and cross-vehicle key reuse returns
  `idempotency_conflict`;
- full capacity returns `no_available_slot` without partial writes;
- pre-occupied slots are never selected; and
- parking status returns five correctly ordered slots with active-session
  details.

The complete test suite, Ruff, and `git diff --check` must pass before the
milestone is marked complete.

## Documentation

The public endpoint examples are added to `README.md`. The idempotency and
transaction decisions are appended to `decisions.md`. On completion,
`progress.md` records the milestone evidence and identifies the vision
occupancy pipeline as the next feature.
