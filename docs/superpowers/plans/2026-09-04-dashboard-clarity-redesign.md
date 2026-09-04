# Dashboard Clarity Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the stylized dark dashboard with a restrained light interface and make successful or failed exit operations unmistakably visible beside the RFID controls.

**Architecture:** Keep the existing FastAPI route and JSON APIs unchanged. Restructure the static HTML around parking status, vehicle access, current vehicles, operations, and optimizer history; update the browser renderer to drive persistent local operation feedback from the existing API responses.

**Tech Stack:** Semantic HTML, CSS, browser JavaScript, FastAPI TestClient, pytest, Playwright CLI

**Spec:** `docs/superpowers/specs/2026-09-04-dashboard-clarity-redesign-design.md`

## Global Constraints

- Do not change parking API or persistence contracts.
- Use no remote fonts, icon libraries, gradients, frontend framework, or new dependency.
- The exit result stays visible beside the RFID controls after status refresh.
- The current-vehicle list is derived only from `/api/parking/status`.
- Free, occupied, success, and failure states use text as well as color.
- The layout remains usable without horizontal page scrolling at 390px width.

---

### Task 1: Operation Feedback and Current-Vehicle Structure

**Files:**
- Modify: `backend/app/dashboard/index.html`
- Modify: `tests/test_dashboard.py`

**Interfaces:**
- Produces: `#operation-result[role="status"][aria-live="polite"]` beside the RFID buttons.
- Produces: `#current-vehicles` for live rows derived from slot status.
- Removes: `#latest-assignment` and the separate screen-reader-only announcement.

- [ ] **Step 1: Write the failing document-contract test**

```python
def test_dashboard_places_operation_feedback_and_vehicles_by_controls(
    tmp_path: Path,
) -> None:
    with TestClient(create_app(make_settings(tmp_path))) as client:
        document = client.get("/dashboard").text

    assert 'id="operation-result" role="status" aria-live="polite"' in document
    assert 'id="current-vehicles"' in document
    assert 'id="latest-assignment"' not in document
    assert document.index('id="operation-result"') < document.index(
        'id="current-vehicles"'
    )
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `.venv/bin/python -m pytest tests/test_dashboard.py::test_dashboard_places_operation_feedback_and_vehicles_by_controls -v`
Expected: FAIL because `operation-result` and `current-vehicles` do not exist.

- [ ] **Step 3: Restructure the semantic document**

Replace the marketing hero and numbered control-room sections with a compact
header, Overview heading, Availability summary, Parking spaces, Vehicle access,
Current parked vehicles, Recent operations, and Optimizer history. Put this
initial result region directly after the form buttons:

```html
<div id="operation-result" class="operation-result operation-result--idle"
     role="status" aria-live="polite">
  Enter an RFID identifier to simulate vehicle access.
</div>
```

Add `<div id="current-vehicles" class="vehicle-list">No active vehicles.</div>`
beside the access card. Remove the old latest-assignment and global announcement
regions.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_dashboard.py -v`
Expected: all dashboard document tests pass.

- [ ] **Step 5: Commit the new information structure**

```bash
git add backend/app/dashboard/index.html tests/test_dashboard.py
git commit -m "refactor: simplify dashboard structure"
```

---

### Task 2: Visible Exit Result and Current-Vehicle Rendering

**Files:**
- Modify: `backend/app/dashboard/dashboard.js`

**Interfaces:**
- Consumes: existing entry, exit, parking-status, and optimizer-history JSON.
- Produces: `renderOperationResult(kind, message)`, `renderCurrentVehicles(slots)`, and persistent success/error feedback.

- [ ] **Step 1: Establish the failing real-browser regression**

Start the app with a fresh database, open `/dashboard`, enter `EXIT-REGRESSION-1`,
click entry, then exit. Verify the old page lacks a result region beside the
controls and cannot display the required sentence
`EXIT-REGRESSION-1 exited successfully. S1 is now available.`

- [ ] **Step 2: Bind the new dashboard elements**

Replace the `assignment` and `announcement` bindings with:

```javascript
operationResult: document.querySelector("#operation-result"),
currentVehicles: document.querySelector("#current-vehicles"),
```

- [ ] **Step 3: Implement persistent operation feedback**

Add `renderOperationResult(kind, message)` to replace idle/loading/success/error
classes and assign message text with `textContent`. Before a request, render
`Processing entry…` or `Processing exit…`. On success render exactly:

```javascript
const message = operation === "entry"
  ? `${rfidUid} entered and was assigned ${payload.slot_name}.`
  : `${rfidUid} exited successfully. ${payload.slot_name} is now available.`;
renderOperationResult("success", message);
```

On failure render `renderOperationResult("error", error.message)`. Do not modify
the result from `refreshDashboard`. After a successful request call
`elements.uid.focus()` and `elements.uid.select()`.

- [ ] **Step 4: Render current vehicles from status**

Add `renderCurrentVehicles(slots)` and call it from `renderStatus`. Filter slots
whose `active_session_id` is non-null. Render each as a row containing RFID,
slot name, and zone using created elements and `textContent`; when empty render
one element containing exactly `No active vehicles.`

- [ ] **Step 5: Run the browser regression and verify GREEN**

With a fresh database, verify entry shows the entry sentence, one occupied slot,
and one current vehicle. Verify exit shows the exact exit sentence, five free
slots, and `No active vehicles.` Verify a second exit shows its error beside the
controls. Confirm the console has no unexpected JavaScript errors.

- [ ] **Step 6: Commit the behavior fix**

```bash
git add backend/app/dashboard/dashboard.js
git commit -m "fix: surface vehicle exit results"
```

---

### Task 3: Restrained Light Visual System and Final Verification

**Files:**
- Modify: `backend/app/dashboard/dashboard.css`
- Modify: `README.md`
- Modify: `progress.md`

**Interfaces:**
- Produces: responsive light operational styling for the Task 1 structure and Task 2 states.
- Documents: visible entry/exit feedback in the presenter flow.

- [ ] **Step 1: Capture the old desktop and mobile baselines**

Use Playwright at 1440x1000 and 390x844. Confirm the old design contains the
dark/neon palette, oversized hero, numbered labels, decorative grid, and large
background parking letters identified by the approved spec.

- [ ] **Step 2: Replace the visual system**

Use a `#f5f6f8` page, white cards, `#20242a` text, `#667085` secondary text,
`#dfe3e8` borders, `#1769e0` primary action/focus, `#16834a` free/success, and
`#c53933` occupied/error. Use only solid fills. Apply standard sentence case,
14–28px type sizes, 8–16px spacing increments, 12px card radius, and subtle
`0 1px 2px rgba(16,24,40,.05)` shadows. Stack all two-column sections below
760px and prevent table overflow from widening the page.

- [ ] **Step 3: Verify desktop and mobile presentation**

At 1440x1000 verify Vehicle access and Current parked vehicles appear together
without scrolling, operation feedback is adjacent to the controls, and all five
spaces are readable. At 390x844 verify no horizontal page overflow, buttons are
full-width, and status text remains visible without relying on color.

- [ ] **Step 4: Update user documentation and progress**

Change the presenter flow to explicitly point out the persistent operation
message and current-vehicle removal on exit. Record the redesign and exit
regression verification under the completed dashboard milestone without
changing unfinished vision, prediction, firmware, or full end-to-end statuses.

- [ ] **Step 5: Run the final gate**

Run:

```bash
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
git diff --check
```

Expected: the full test suite passes, Ruff reports no errors, and whitespace
check is silent.

- [ ] **Step 6: Commit the verified redesign**

```bash
git add backend/app/dashboard/dashboard.css README.md progress.md
git commit -m "style: refine dashboard presentation"
```

- [ ] **Step 7: Verify and push the committed tree**

Run the full test suite and Ruff again, confirm the worktree is clean, then push
`feat/demo-parking-lifecycle` to `origin` under the user's existing branch-push
authorization.
