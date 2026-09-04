# Scalable Vision Occupancy Pipeline Design

## Scope

Milestone 4 adds a hardware-independent camera occupancy pipeline while making
slot cardinality configuration-driven throughout the existing backend. The
committed demo configuration continues to define five slots, but configuration,
persistence, allocation, lifecycle, status, and vision contracts operate on any
non-empty set of uniquely identified slots.

This milestone includes ROI configuration, deterministic heuristic detection,
temporal smoothing, atomic persistence of accepted changes, and
`POST /api/camera/occupancy`. It does not add camera polling, a trained CNN,
prediction models, dashboard views, or firmware changes.

## Architecture

The feature has five focused boundaries:

- `backend/app/config.py` validates a non-empty parking-slot collection and a
  matching ROI configuration without imposing a fixed cardinality.
- `vision/detector.py` decodes image bytes, validates ROI bounds, crops every
  configured region, and classifies each crop through a detector interface.
- `backend/app/services/occupancy.py` owns confidence filtering, per-slot
  temporal smoothing, lifecycle safety rules, and persistence coordination.
- `backend/app/db.py` owns the atomic accepted-transition transaction and the
  data-preserving migration away from the legacy five-slot database constraint.
- `backend/app/routes/occupancy.py` owns the multipart image endpoint and maps
  typed input/domain failures to structured HTTP errors.

The detector and smoothing policy remain independent: a future CNN can replace
the heuristic without changing API, persistence, or temporal behavior.

## Configurable Slot Cardinality

`ParkingConfig.slots` must contain at least one slot. Slot IDs are positive,
unique integers and names are unique; IDs need not be contiguous. The order in
the YAML file is the canonical response order.

All existing fixed-size validation is removed from parking models, allocation
models, health checks, and database initialization. Allocation requests accept
one or more unique candidates and preserve deterministic tie-breaking by slot
ID. GA, PSO, and ACO continue to receive identical immutable candidate sets and
exclude occupied candidates before searching.

The committed `config/parking.yaml` remains a five-slot demonstration. This
preserves the physical prototype while allowing another deployment to change
slot count through configuration only.

## ROI Configuration

The committed `config/rois.example.json` provides a runnable demo layout and is
the default in demo mode. Deployments may override `SMART_PARKING_ROI_CONFIG_PATH`
with an ignored calibrated file.

`Settings.camera_max_image_bytes` defaults to 5 MiB and is configurable through
`SMART_PARKING_CAMERA_MAX_IMAGE_BYTES`.

The document contains detector policy and a list of regions:

```json
{
  "heuristic": {
    "edge_threshold": 0.12,
    "minimum_confidence": 0.70,
    "required_consecutive_frames": 3
  },
  "slots": [
    {"slot_id": 1, "x": 0, "y": 0, "width": 160, "height": 120}
  ]
}
```

Coordinates are integer pixels with a non-negative origin and positive width
and height. ROI slot IDs must match the configured parking slot IDs exactly:
no missing, unknown, or duplicate mappings are accepted. Each uploaded image
must contain every configured rectangle completely; otherwise the request is
rejected without changing smoothing or database state.

## Heuristic Detector

The deterministic baseline converts each ROI to 8-bit grayscale, applies
Pillow's `FIND_EDGES` filter, and calculates the fraction of pixels whose edge
intensity is at least 128. That edge density is the normalized score in
`[0, 1]`. A score greater than or equal to the configured edge threshold is an
occupied candidate. Confidence is `1 - score / threshold` for a free candidate
and `(score - threshold) / (1 - threshold)` for an occupied candidate, clamped
to `[0, 1]`. Values at the decision boundary therefore have zero confidence and
values at either endpoint have full confidence.

The detector returns one immutable observation per configured ROI containing
slot ID, candidate occupied state, score, and confidence. Pillow and NumPy are
the only runtime dependencies; TensorFlow is not loaded by this milestone.

The heuristic is a deterministic, calibratable demo baseline rather than a
claim of production image accuracy. A future detector implementation must
return the same observation contract.

## Temporal Smoothing and Safety

The occupancy service keeps a pending candidate and consecutive-frame count for
each configured slot. A confident candidate different from the currently
accepted database state must appear for the configured number of consecutive
frames before it is accepted. An uncertain observation or a candidate matching
the accepted state clears that slot's pending streak. Process restart also
clears pending streaks while leaving accepted database state intact.

Each observation receives one outcome:

- `unchanged`: candidate equals the accepted state;
- `pending`: a confident state change has not reached the required streak;
- `accepted`: the streak completed and the state was persisted; or
- `blocked`: a free transition would conflict with an active parking session.

A camera transition may mark an otherwise unreserved slot occupied. It may not
mark a slot free while that slot has an active parking session, because the
current schema intentionally combines allocation reservation and accepted
occupancy in `parking_slots.occupied`. The database rechecks this rule inside
the reserved transaction so a concurrent lifecycle change cannot be bypassed.
A blocked transition clears its pending streak and leaves durable state
unchanged.

## Persistence and Migration

Accepted changes from one frame are persisted in one `BEGIN IMMEDIATE`
transaction. For every accepted slot, the transaction updates
`parking_slots.occupied` and `updated_at` and inserts one `occupancy_events` row
with the detector confidence, `source = 'camera_heuristic'`, and one shared
timezone-aware UTC observation timestamp. Pending, uncertain, unchanged, and
blocked observations do not create events.

Legacy databases contain `CHECK (id BETWEEN 1 AND 5)` on `parking_slots`.
Initialization detects that schema and rebuilds the table without the fixed
upper bound while preserving rows and foreign-key relationships. The migration
is idempotent and runs transactionally. Configuration seeding upserts configured
slots but does not silently delete historical slots; initialization rejects a
database whose existing slot set conflicts with the configured set until a
future explicit removal policy exists.

If any accepted update or event insert fails, the complete frame transaction
rolls back and the in-memory smoothing state is not advanced past the failed
commit.

## Camera API Contract

`POST /api/camera/occupancy` accepts one multipart field named `image`. The
field must contain a non-empty payload within the configured request-size limit
that Pillow decodes with format `JPEG`. The endpoint processes all configured
slots and returns:

```json
{
  "detector": "heuristic",
  "observed_at": "2026-09-04T10:00:00.000Z",
  "slots": [
    {
      "slot_id": 1,
      "candidate_occupied": true,
      "accepted_occupied": false,
      "score": 0.45,
      "confidence": 0.82,
      "outcome": "pending",
      "consecutive_frames": 1
    }
  ]
}
```

The `slots` array has the same cardinality and ordering as the configured
parking slots. `accepted_occupied` always reflects durable state after the
request completes.

Stable structured input errors are:

- `empty_image` for an empty upload;
- `image_too_large` when the payload exceeds the configured limit;
- `invalid_image` when Pillow cannot decode a JPEG; and
- `roi_out_of_bounds` when the image does not contain every ROI.

These errors use HTTP 400 except `image_too_large`, which uses HTTP 413.
FastAPI multipart/schema validation remains HTTP 422. No input error modifies
smoothing or persistent state.

## Testing

Development follows red-green-refactor. Unit tests use generated grayscale and
patterned JPEG fixtures so results are deterministic and require no dataset or
hardware.

Coverage includes:

- one, five, larger, and non-contiguous slot configurations;
- rejection of empty slot sets, duplicate IDs/names, and ROI mapping mismatch;
- allocation and lifecycle behavior with dynamic candidate counts;
- idempotent, data-preserving migration from the legacy five-slot table;
- deterministic heuristic scoring, classification, and confidence;
- ROI ordering and out-of-bounds rejection;
- independent per-slot streaks and uncertain-frame reset;
- no state change from a single confident frame;
- atomic accepted slot/event persistence and rollback on failure;
- active-session protection for camera-reported free transitions;
- empty, oversized, non-JPEG, and undersized image errors; and
- complete multipart upload through detector, smoothing, persistence, response,
  and parking-status visibility.

The focused tests, full test suite, Ruff, and `git diff --check` must pass before
the milestone is marked complete.

## Documentation and Project State

`README.md` will document scalable configuration, ROI calibration, heuristic
limitations, and camera request/response examples. `architecture.md` and the
decision log will clarify that five slots are the default deployment rather
than a software invariant. `progress.md` will record verification evidence and
identify prediction comparison as the next milestone after completion.
