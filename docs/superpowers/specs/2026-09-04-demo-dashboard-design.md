# Demo Dashboard Design

## Scope

Add a polished, hardware-independent dashboard at `GET /dashboard` for the
features that work today. The page visualizes all five parking slots, simulates
RFID entry and exit operations, highlights the latest assignment, reports
recent activity, and shows persisted optimizer benchmark results.

Prediction and camera controls are excluded until their backend contracts
exist. The dashboard must not show controls that appear usable but cannot
complete an operation.

## Architecture

FastAPI serves one static HTML document plus versioned CSS and JavaScript files
from a dedicated dashboard package. The browser consumes the existing JSON API
without adding a frontend framework, template engine, Node.js toolchain, or new
runtime dependency.

The dashboard JavaScript is split into small responsibilities:

- an API client owns HTTP requests and structured error parsing;
- rendering functions update slot, summary, assignment, activity, and
  benchmark regions;
- form handlers create unique operation keys and submit simulated RFID entry
  or exit requests; and
- a refresh coordinator polls status and benchmark data without overlapping
  requests.

The FastAPI application mounts static assets at `/static/dashboard` and serves
the dashboard document at `/dashboard`.

## Visual Structure

The page uses a responsive dark control-room presentation suitable for a
laptop or projector. It contains:

1. A top bar with the Smart Parking title, demo-mode badge, live connection
   indicator, and last-refresh time.
2. A summary row with total, available, occupied, and active-session counts.
3. A five-card parking grid. Each card shows slot name, free/occupied state,
   zone, walking distance, and assigned RFID when available.
4. A control panel with one RFID field and separate `Simulate Entry` and
   `Simulate Exit` buttons.
5. A latest-assignment panel showing the vehicle, selected slot, optimizer,
   cost, and gate action after entry. Before an entry it shows a useful empty
   state.
6. A recent-activity list maintained for the current browser session.
7. An optimizer benchmark table populated from persisted benchmark runs, with
   an informative empty state when no comparisons have been run.

Color is never the only status signal: slot cards include text and icons, the
connection indicator includes a label, and activity notices include readable
messages.

## Data Flow

On page load, the browser fetches `/api/parking/status` and
`/api/benchmarks/optimizers` in parallel. Parking status refreshes every two
seconds. Benchmark results refresh after initial load and after an entry, since
entry persists the selected optimizer run.

For entry and exit, the browser trims and uppercases the RFID value, rejects an
empty value locally, and generates a unique key with the operation type,
current timestamp, and a random UUID when available. It posts to the existing
vehicle endpoint, renders the result, records an activity item, then refreshes
status. Buttons are disabled while an operation is in flight to prevent
accidental double submission.

The server remains the source of truth. Browser state improves presentation
but never decides whether a slot is occupied or whether a lifecycle transition
is valid.

## Error and Empty States

The API client reads FastAPI's structured `detail.code` and `detail.message`
payload. Expected conflicts appear as friendly notices while retaining their
stable code for diagnosis. Network failures set the connection indicator to
offline and leave the most recently rendered slot state visible rather than
blanking the dashboard.

The page provides explicit states for:

- loading initial parking data;
- no optimizer benchmark history;
- no latest assignment yet;
- invalid or empty RFID input;
- full capacity and lifecycle conflicts; and
- backend connection loss and recovery.

Polling errors do not append repeated activity entries every two seconds. A
single offline event is recorded, followed by one recovery event when polling
succeeds again.

## Accessibility and Responsive Behavior

The document uses semantic headings, forms, labels, tables, buttons, and live
status regions. Keyboard focus is clearly visible, status announcements use an
appropriate ARIA live region, and reduced-motion preferences disable decorative
transitions.

The desktop layout shows the parking grid and control/assignment panels side by
side. Narrow screens collapse to one column, preserve readable table overflow,
and keep all operations usable without horizontal page scrolling.

## Testing

Backend integration tests use the real FastAPI application and assert that:

- `GET /dashboard` returns the dashboard document and required landmarks;
- CSS and JavaScript assets are served with the correct content types;
- the document references only local dashboard assets; and
- the existing entry, exit, status, and benchmark endpoints remain available.

JavaScript logic is organized around pure rendering and formatting helpers
where practical, but version 1 avoids introducing a Node.js test toolchain.
The end-to-end browser behavior is verified with a smoke scenario: load the
dashboard, submit an RFID entry, observe the assigned occupied slot, submit an
exit, and observe the slot return to free.

Final verification requires the full Python test suite, Ruff, whitespace
checks, and the browser smoke scenario.

## Documentation and Completion

The README gains a dashboard run path and a short presenter flow. The progress
record marks the dashboard milestone complete only after the automated and
browser verification pass. The implementation stays on the existing
`feat/demo-parking-lifecycle` branch so the backend lifecycle and its dashboard
can be reviewed as one demo-ready vertical slice.
