# Dashboard Clarity Redesign

## Purpose

Replace the current stylized control-room dashboard with a restrained light
operational interface and make every vehicle exit visibly confirm its result
near the control that initiated it.

The parking API and persistence behavior remain unchanged. This work corrects
the browser presentation and interaction hierarchy.

## Diagnosed Exit-Feedback Problem

The exit API succeeds and the browser renders the released slot, but the result
is easy to miss. Confirmation appears only in the adjacent assignment panel and
the activity list farther down the page. There is no operation result next to
the RFID controls, and an invalid exit is visible only in recent activity.

The dashboard therefore needs a persistent, local result region within the
vehicle-access card. Success or failure must remain visible until the next
operation begins. An exit success must state the vehicle, released slot, and
new availability in one sentence.

## Visual Direction

Use a clean light operational UI:

- soft gray page canvas;
- white surfaces with subtle neutral borders;
- charcoal body text and muted gray supporting text;
- green only for free/success states;
- red only for occupied/error states; and
- a restrained blue accent for primary actions and focus.

Remove the oversized marketing hero, neon palette, ambient decoration, grid
background, translucent panels, large background letters, numbered section
labels, excessive uppercase text, and control-room terminology. Typography uses
the local system font stack with conventional weights and comfortable line
height. No remote fonts, icon libraries, gradients, or frontend dependencies
are added.

## Information Architecture

The page contains a compact application header followed by five sections:

1. **Overview** — page title, concise description, connection status, and last
   update time.
2. **Availability** — total, available, occupied, and active-vehicle summary
   values in one compact strip.
3. **Parking spaces** — five equal cards showing name, status, zone, walking
   distance, and current RFID when occupied.
4. **Vehicle access** — RFID field, Enter and Exit actions, and the persistent
   operation-result region directly below the buttons.
5. **Operational details** — current parked vehicles, recent operations, and
   optimizer history in compact cards.

The desktop layout places Vehicle access beside Current parked vehicles so the
effect of an entry or exit is visible without scrolling. Recent operations and
optimizer history appear below. At narrow widths all sections stack in reading
order without horizontal page scrolling.

## Entry and Exit Feedback

When an operation starts, the result region shows a neutral progress message
and the buttons are disabled.

On entry success, the result region becomes a green success notice containing:

`DEMO-CARD-1 entered and was assigned S1.`

On exit success, it becomes a green success notice containing:

`DEMO-CARD-1 exited successfully. S1 is now available.`

The dashboard then refreshes parking status and optimizer history. The released
space must render as Free, and the exited vehicle must disappear from Current
parked vehicles. The success notice remains visible after refresh, and the RFID
field is selected so the presenter can immediately type another identifier.

On failure, the result region becomes a red error notice with the friendly
domain message. The same event is also recorded once in Recent operations.
Status refresh does not erase operation feedback.

## Current Parked Vehicles

Derive the current vehicle list from `/api/parking/status`. Every slot with a
non-null active session is rendered as one row containing RFID, slot name, and
zone. If no vehicle is parked, show `No active vehicles.`

This list is presentation-only. It does not create a second source of state and
does not introduce a new endpoint.

## Existing Data Flow

The browser continues polling `/api/parking/status` and
`/api/benchmarks/optimizers` every two seconds with the existing non-overlap
guard. Entry and exit continue using `/api/vehicle/entry` and
`/api/vehicle/exit` with browser-generated idempotency keys. API errors continue
to use the structured FastAPI conflict payload.

The latest assignment panel is removed. The operation result and current
vehicle list provide a more direct explanation of current state, while Recent
operations retains historical entry and exit context.

## Accessibility

The operation-result region uses `role="status"` and `aria-live="polite"`.
Errors remain visible as text and do not rely on color. Free and occupied cards
include status words in addition to color. All form controls retain visible
labels, keyboard focus indicators, and disabled states. Motion is limited to
short opacity changes and disabled for reduced-motion preferences.

## Verification

Test-driven implementation adds a dashboard document contract for the result
region and current-vehicles region. A real-browser regression scenario must:

1. load five free spaces;
2. submit an entry and observe the entry success notice, one occupied space,
   and one current vehicle;
3. submit an exit with the same RFID and observe the exact exit success notice,
   five free spaces, and `No active vehicles.`; and
4. submit an invalid exit and observe the error beside the controls.

The dashboard is visually inspected at desktop and mobile widths. The complete
Python test suite, Ruff, and whitespace checks must pass before the redesign is
marked complete and pushed.
