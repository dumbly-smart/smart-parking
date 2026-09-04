# Demo Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serve a polished browser dashboard that visualizes five-slot state and drives the working simulated RFID lifecycle.

**Architecture:** FastAPI serves one static HTML document and local CSS/JavaScript assets from `backend/app/dashboard`. Browser code calls the existing status, vehicle, and optimizer benchmark APIs; the backend remains the only source of parking truth.

**Tech Stack:** Python 3.11+, FastAPI, Starlette static files, semantic HTML, CSS, browser JavaScript, pytest, Playwright CLI

**Spec:** `docs/superpowers/specs/2026-09-04-demo-dashboard-design.md`

## Global Constraints

- The dashboard uses server-rendered/static HTML, CSS, and JavaScript without a frontend framework.
- Version 1 shows exactly five parking slots.
- Prediction and camera controls are excluded until their backend contracts exist.
- The page references only local dashboard assets and adds no runtime dependency.
- Parking status refreshes every two seconds without overlapping requests.
- Color is never the only status signal.
- The server remains the source of truth for occupancy and lifecycle decisions.

---

### Task 1: Dashboard Route and Static Asset Boundary

**Files:**
- Create: `backend/app/dashboard/__init__.py`
- Create: `backend/app/dashboard/index.html`
- Create: `backend/app/dashboard/dashboard.css`
- Create: `backend/app/dashboard/dashboard.js`
- Create: `backend/app/routes/dashboard.py`
- Modify: `backend/app/main.py`
- Create: `tests/test_dashboard.py`

**Interfaces:**
- Consumes: `FastAPI`, `StaticFiles`, `FileResponse`.
- Produces: `GET /dashboard`, `/static/dashboard/dashboard.css`, and `/static/dashboard/dashboard.js`.

- [ ] **Step 1: Write the failing page and asset integration tests**

```python
def test_dashboard_serves_semantic_local_document(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path))) as client:
        response = client.get("/dashboard")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert '<main id="dashboard"' in response.text
    assert 'action="/api/vehicle/entry"' not in response.text
    assert 'src="/static/dashboard/dashboard.js"' in response.text
    assert 'href="/static/dashboard/dashboard.css"' in response.text
    assert "https://" not in response.text


@pytest.mark.parametrize(
    ("path", "content_type"),
    [
        ("/static/dashboard/dashboard.css", "text/css"),
        ("/static/dashboard/dashboard.js", "text/javascript"),
    ],
)
def test_dashboard_assets_are_served(
    tmp_path: Path, path: str, content_type: str
) -> None:
    with TestClient(create_app(make_settings(tmp_path))) as client:
        response = client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(content_type)
```

- [ ] **Step 2: Run the route tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_dashboard.py -v`
Expected: FAIL because `/dashboard` returns 404.

- [ ] **Step 3: Add the dashboard package and route**

```python
DASHBOARD_DIRECTORY = Path(__file__).resolve().parents[1] / "dashboard"

router = APIRouter()


@router.get("/dashboard", response_class=FileResponse)
def dashboard() -> FileResponse:
    return FileResponse(DASHBOARD_DIRECTORY / "index.html", media_type="text/html")
```

Mount `StaticFiles(directory=DASHBOARD_DIRECTORY)` at `/static/dashboard` and
include the dashboard router in `create_app`. Add minimal valid local HTML, CSS,
and JavaScript files so all three paths respond successfully.

- [ ] **Step 4: Run focused and regression tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_dashboard.py tests/test_foundation.py -v`
Expected: all tests pass.

- [ ] **Step 5: Commit the serving boundary**

```bash
git add backend/app/dashboard backend/app/routes/dashboard.py backend/app/main.py tests/test_dashboard.py
git commit -m "feat: serve dashboard and local assets"
```

---

### Task 2: Accessible Dashboard Layout and Visual System

**Files:**
- Modify: `backend/app/dashboard/index.html`
- Modify: `backend/app/dashboard/dashboard.css`
- Modify: `tests/test_dashboard.py`

**Interfaces:**
- Produces DOM IDs: `connection-status`, `last-refresh`, `total-count`, `available-count`, `occupied-count`, `active-count`, `parking-grid`, `rfid-form`, `rfid-uid`, `entry-button`, `exit-button`, `latest-assignment`, `activity-list`, `benchmark-body`, and `announcement`.
- Produces reusable CSS state classes: `slot--free`, `slot--occupied`, `status--online`, `status--offline`, `activity--success`, and `activity--error`.

- [ ] **Step 1: Extend the failing document-contract test**

```python
def test_dashboard_contains_accessible_demo_controls(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path))) as client:
        document = client.get("/dashboard").text
    for expected in (
        '<main id="dashboard"',
        'id="parking-grid"',
        'id="rfid-form"',
        'for="rfid-uid"',
        'id="entry-button"',
        'id="exit-button"',
        'id="latest-assignment"',
        'id="activity-list"',
        'id="benchmark-body"',
        'id="announcement" role="status" aria-live="polite"',
    ):
        assert expected in document
```

- [ ] **Step 2: Run the document-contract test and verify RED**

Run: `.venv/bin/python -m pytest tests/test_dashboard.py::test_dashboard_contains_accessible_demo_controls -v`
Expected: FAIL on the first missing dashboard landmark.

- [ ] **Step 3: Build the semantic dashboard document**

Add a skip link, header, summary cards, five-card parking region, RFID form with
two explicit submit buttons, latest-assignment article, session activity list,
optimizer table, and polite live announcement. Use visible labels and readable
empty/loading messages for every dynamic region.

- [ ] **Step 4: Implement the responsive control-room visual system**

Define local custom properties for ink, panel, cyan, green, amber, and red;
create a two-column desktop layout, five-card grid, high-contrast focus ring,
responsive single-column breakpoint at `800px`, table overflow containment,
and a `prefers-reduced-motion: reduce` rule that removes transitions and
animations.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_dashboard.py -v`
Expected: all dashboard tests pass.

- [ ] **Step 6: Commit the visual shell**

```bash
git add backend/app/dashboard/index.html backend/app/dashboard/dashboard.css tests/test_dashboard.py
git commit -m "feat: design accessible parking dashboard"
```

---

### Task 3: Live Status, Lifecycle Controls, and Benchmark Rendering

**Files:**
- Modify: `backend/app/dashboard/dashboard.js`
- Modify: `backend/app/dashboard/index.html`
- Modify: `tests/test_dashboard.py`

**Interfaces:**
- Consumes: `GET /api/parking/status`, `POST /api/vehicle/entry`, `POST /api/vehicle/exit`, and `GET /api/benchmarks/optimizers`.
- Produces: `apiRequest(path, options)`, `renderStatus(payload)`, `renderAssignment(payload)`, `renderBenchmarks(payload)`, `addActivity(kind, title, detail)`, `submitVehicleOperation(operation)`, and `refreshDashboard()`.

- [ ] **Step 1: Add a failing JavaScript behavior-contract test**

```python
def test_dashboard_script_connects_working_demo_apis(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path))) as client:
        script = client.get("/static/dashboard/dashboard.js").text
    for contract in (
        '"/api/parking/status"',
        '"/api/benchmarks/optimizers"',
        '`/api/vehicle/${operation}`',
        "setInterval(refreshDashboard, 2000)",
        "crypto.randomUUID",
    ):
        assert contract in script
```

- [ ] **Step 2: Run the behavior-contract test and verify RED**

Run: `.venv/bin/python -m pytest tests/test_dashboard.py::test_dashboard_script_connects_working_demo_apis -v`
Expected: FAIL because the minimal script does not call the APIs.

- [ ] **Step 3: Implement API and rendering helpers**

`apiRequest` must parse JSON, map `detail.code` and `detail.message` into an
`Error` with a readable message, and throw a network error unchanged.
`renderStatus` must render five slot articles, update all four counts, preserve
free/occupied text, and include active RFID data. `renderBenchmarks` must show
the latest ten persisted runs or one empty row. All user-provided strings must
be assigned with `textContent`, never concatenated into `innerHTML`.

- [ ] **Step 4: Implement entry and exit interactions**

On form submission, read `event.submitter.dataset.operation`, trim and uppercase
the RFID UID, reject empty input, create
`${operation}-${Date.now()}-${crypto.randomUUID?.() ?? fallback}`, disable both
buttons, post JSON, render entry assignment or exit activity, refresh status and
benchmarks, then re-enable buttons in `finally`.

- [ ] **Step 5: Implement non-overlapping polling and connectivity states**

Guard `refreshDashboard` with an `isRefreshing` boolean. On first failure,
render `Offline` and add one error activity; suppress repeated offline events.
On the next success, render `Live`, add one recovery activity, and update the
last-refresh time. Call once at startup and schedule
`setInterval(refreshDashboard, 2000)`.

- [ ] **Step 6: Run focused and full tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_dashboard.py -v`

Run: `.venv/bin/python -m pytest`

Expected: all tests pass.

- [ ] **Step 7: Commit live dashboard behavior**

```bash
git add backend/app/dashboard tests/test_dashboard.py
git commit -m "feat: add live dashboard interactions"
```

---

### Task 4: Browser Smoke Verification and Demo Documentation

**Files:**
- Modify: `README.md`
- Modify: `progress.md`
- Test: `tests/test_dashboard.py`

**Interfaces:**
- Documents: one-command server start, dashboard URL, and presenter flow.
- Verifies: browser entry updates one slot to occupied and exit returns it to free.

- [ ] **Step 1: Start the application against a disposable demo database**

Run:

```bash
SMART_PARKING_DATABASE_URL=sqlite:////tmp/smart-parking-dashboard.db \
  .venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Expected: Uvicorn reports startup complete and `GET /dashboard` returns 200.

- [ ] **Step 2: Run the real-browser lifecycle smoke scenario**

Open `http://127.0.0.1:8000/dashboard`, confirm five free slot cards and the
Live indicator, enter `DEMO-CARD-1`, click `Simulate Entry`, confirm one card
shows Occupied and the assignment panel shows the same RFID and slot, click
`Simulate Exit`, and confirm all five cards show Free again. Capture a desktop
screenshot for visual inspection and verify the browser console has no errors.

- [ ] **Step 3: Add README presenter instructions**

Document `make run`, `http://127.0.0.1:8000/dashboard`, the entry/status/exit
sequence, and that API documentation remains at `/docs`.

- [ ] **Step 4: Run the final verification gate**

Run:

```bash
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
git diff --check
```

Expected: the complete suite passes, Ruff reports no errors, and diff check is
silent.

- [ ] **Step 5: Update progress with observed evidence**

Mark Dashboard complete with the actual test count and successful browser smoke
scenario. Keep Vision occupancy pipeline, Prediction comparison, Firmware
integration, and End-to-end demo accurately marked as incomplete.

- [ ] **Step 6: Commit the verified dashboard milestone**

```bash
git add README.md progress.md
git commit -m "docs: complete dashboard milestone"
```

- [ ] **Step 7: Verify the committed tree**

Run:

```bash
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
git diff --check
git status --short
```

Expected: all tests pass, Ruff passes, diff check is silent, and the worktree is
clean.
