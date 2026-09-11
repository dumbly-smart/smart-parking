# Dashboard and Simulated Demo Design

## Purpose

Deliver a framework-free operational dashboard at `GET /dashboard` and a
repeatable, hardware-independent demonstration that exercises the existing
parking lifecycle and makes its results visible in that dashboard.

## Scope

The dashboard is a server-served HTML document with static CSS and JavaScript.
It is a read-only observer of the public API contracts already owned by the
backend. It does not reproduce allocation, occupancy, prediction, benchmark,
or persistence logic in browser code.

The browser polls these existing APIs:

- `GET /api/parking/status`
- `GET /api/benchmarks/optimizers`
- `GET /api/benchmarks/predictors`
- `GET /api/prediction`

The only dashboard-specific server data is minimal, non-sensitive bootstrapped
configuration: the selected optimizer and selected predictor. It is embedded
in the HTML document by the dashboard route so no additional API contract is
needed.

## Dashboard behavior

The initial HTML provides stable regions for a status summary, slot grid,
optimizer comparison, predictor comparison, and forecast. The static
JavaScript fetches the four API resources together at load and on a fixed
refresh interval. A failed refresh displays a human-readable dashboard error
without replacing the last successfully rendered state.

Slot cards are created from `status.slots`, in the returned order. Each card
shows only slot metadata needed to operate the lot: name, zone, occupancy, and
last-update time. It intentionally never reads or renders `rfid_uid` or
`active_session_id`, even though status includes them for hardware/lifecycle
clients. This makes changing configured slot count a data-only change.

The selected optimizer comes from the dashboard bootstrap. The optimizer table
renders persisted runs returned by `GET /api/benchmarks/optimizers`, including
algorithm, chosen slot, cost, iterations, runtime, and timestamp. The selected
predictor comes from the bootstrap. The forecast panel renders actual returned
model, predicted occupancy, aligned `target_at`, and the stable fallback reason
when present. The predictor table renders model, MAE, MSE, RMSE, and inference
latency from `GET /api/benchmarks/predictors`; artifact identifiers and split
IDs are not shown because they do not aid normal operation.

No dashboard view or dashboard-specific response contains RFID identifiers.
The existing vehicle endpoints retain their backward-compatible RFID contracts
for controllers and the simulator.

## Simulated end-to-end demo

A new command-line script is the simulation driver, rather than adding vehicle
controls to the browser. It talks to the existing public HTTP contracts using
the Python standard library and accepts a configurable base URL and deterministic
RFID/idempotency values. It performs a simulated entry, triggers an optimizer
comparison over the current status-derived candidates, reads the prediction,
and prints a privacy-safe summary that omits its RFID input. The dashboard then
observes the resulting status and persisted optimizer data through its normal
polling API calls.

Camera simulation remains outside this first script because the existing camera
endpoint requires a real JPEG and configured ROI geometry. The demonstration is
still complete without hardware because lifecycle, allocation comparison,
prediction fallback, and UI are all exercised deterministically. A caller may
submit an already prepared simulated camera JPEG through the existing endpoint
before or during the demo.

## Server structure

`backend/app/routes/dashboard.py` owns the `GET /dashboard` route and only
selects static assets plus the two safe selected-setting values. `main.py`
registers that router. Static files live in `backend/app/static/`:

- `dashboard.html` is the HTML template with safe JSON bootstrap data.
- `dashboard.css` supplies responsive, accessible visual states.
- `dashboard.js` owns request orchestration and DOM rendering.

FastAPI's `StaticFiles` serves the static directory at `/static`. The route
uses standard-library-safe JSON serialization and marks the bootstrap script as
data rather than executable JavaScript.

## Tests and verification

Route integration tests will prove that `/dashboard` returns HTML, includes the
safe bootstrap values, omits RFID fixture values, and that declared static
assets are available. JavaScript-focused tests will exercise the renderer under
a minimal DOM harness or validate a small, testable rendering contract without
a frontend framework. API integration coverage will populate dynamic configured
slots and persisted comparison data, then confirm the dashboard's API inputs
have the expected shapes and the prediction fallback remains visible.

The implementation follows test-first red/green cycles. Completion requires
focused dashboard and demo tests, full pytest, Ruff, and `git diff --check`.
`progress.md` will record the fresh verification counts and status.

## Compatibility and constraints

- Existing API paths and schemas remain backward compatible.
- The dashboard must not hard-code the five-slot demo cardinality.
- Missing or incompatible prediction artifacts continue to use the existing
  deterministic fallback through `GET /api/prediction`.
- No frontend framework or new runtime dependency is introduced.
- RFID identifiers stay out of dashboard rendering, prediction/comparison data,
  and simulator output.
