# Dashboard and Simulated Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a privacy-safe, framework-free live parking dashboard and a repeatable command-line simulated lifecycle demo.

**Architecture:** FastAPI serves `/dashboard` and static CSS/JavaScript. The browser polls the existing status, optimizer benchmark, predictor benchmark, and prediction APIs; a CLI generates a deterministic JPEG, drives existing camera/lifecycle/allocation APIs, and prints an RFID-free summary.

**Tech Stack:** Python 3.14, FastAPI/Starlette, pytest/TestClient, vanilla HTML/CSS/JavaScript, Python standard library, Ruff, Playwright CLI.

**Spec:** `docs/superpowers/specs/2026-09-12-dashboard-demo-design.md`

## Global Constraints

- Preserve existing API routes and schemas.
- Introduce no frontend framework or runtime dependency.
- Render all returned slots dynamically and in API order.
- Bootstrap only selected optimizer and selected predictor settings.
- Never render RFID identifiers, active session IDs, artifact digests, or filesystem data.
- Keep deterministic prediction fallback inside the existing prediction service.
- Work in `feat/dashboard-demo`; do not push.

---

### Task 1: Dashboard route and asset delivery

**Files:**
- Create: `backend/app/routes/dashboard.py`
- Modify: `backend/app/main.py`
- Create: `backend/app/static/dashboard.html`
- Create: `backend/app/static/dashboard.css`
- Create: `backend/app/static/dashboard.js`
- Test: `tests/test_dashboard.py`

**Interfaces:**
- Consumes: `Settings.selected_optimizer` and `Settings.selected_predictor`.
- Produces: `GET /dashboard`, `/static/dashboard.css`, and `/static/dashboard.js`.

- [ ] **Step 1: Write a failing route integration test**

```python
def test_dashboard_serves_safe_bootstrap_and_assets(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, optimizer="pso", predictor="gru")
    with TestClient(create_app(settings)) as client:
        page = client.get("/dashboard")
        css = client.get("/static/dashboard.css")
        javascript = client.get("/static/dashboard.js")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert '"selected_optimizer": "pso"' in page.text
    assert '"selected_predictor": "gru"' in page.text
    assert css.status_code == 200
    assert javascript.status_code == 200
```

This catches a missing route, missing static mount, or bootstrapping more than the allowlisted configuration.

- [ ] **Step 2: Verify RED**

Run: `/home/xtrmn8/smart-parking/.venv/bin/python -m pytest tests/test_dashboard.py::test_dashboard_serves_safe_bootstrap_and_assets -v`

Expected: FAIL because `/dashboard` returns 404.

- [ ] **Step 3: Implement the minimal route and mount**

```python
STATIC_DIRECTORY = Path(__file__).resolve().parent.parent / "static"
_TEMPLATE = (STATIC_DIRECTORY / "dashboard.html").read_text(encoding="utf-8")

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    bootstrap = json.dumps({
        "selected_optimizer": request.app.state.settings.selected_optimizer,
        "selected_predictor": request.app.state.settings.selected_predictor,
    })
    return HTMLResponse(_TEMPLATE.replace("__DASHBOARD_BOOTSTRAP__", bootstrap))
```

Register the router and `StaticFiles` mount in `create_app`. Link both static assets from the HTML shell.

- [ ] **Step 4: Verify GREEN**

Run: `/home/xtrmn8/smart-parking/.venv/bin/python -m pytest tests/test_dashboard.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/app/routes/dashboard.py backend/app/static tests/test_dashboard.py
git commit -m "feat: serve dashboard shell"
```

### Task 2: Live, dynamic, privacy-safe rendering

**Files:**
- Modify: `backend/app/static/dashboard.html`
- Modify: `backend/app/static/dashboard.css`
- Modify: `backend/app/static/dashboard.js`
- Modify: `tests/test_dashboard.py`

**Interfaces:**
- Consumes: `/api/parking/status`, `/api/benchmarks/optimizers`, `/api/benchmarks/predictors`, `/api/prediction`.
- Produces: dynamic slot cards, selected/runtime model cards, forecast target, comparison tables, refresh/error status.

- [ ] **Step 1: Add failing dynamic-card and API compatibility integration tests**

```python
def test_dashboard_supports_non_five_slot_status_without_exposing_rfid(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, slot_ids=(9, 2, 14))
    with TestClient(create_app(settings)) as client:
        client.post("/api/vehicle/entry", json={
            "rfid_uid": "CARD-PRIVATE", "idempotency_key": "entry-1"
        })
        status = client.get("/api/parking/status")
        page = client.get("/dashboard")
    assert [slot["id"] for slot in status.json()["slots"]] == [9, 2, 14]
    assert 'id="slot-grid"' in page.text
    assert "CARD-PRIVATE" not in page.text
```

Add coverage that the four existing GET APIs respond successfully from the same configured app and that prediction fallback remains `baseline` with a stable reason when history is absent.

- [ ] **Step 2: Verify RED**

Run: `/home/xtrmn8/smart-parking/.venv/bin/python -m pytest tests/test_dashboard.py -v`

Expected: FAIL because the live dashboard regions are absent.

- [ ] **Step 3: Implement DOM rendering and polling**

```javascript
const endpointPaths = [
  "/api/parking/status",
  "/api/benchmarks/optimizers",
  "/api/benchmarks/predictors",
  "/api/prediction",
];

function renderSlots(slots) {
  const cards = slots.map((slot) => {
    const card = document.createElement("article");
    card.dataset.slotId = String(slot.id);
    card.className = slot.occupied ? "slot occupied" : "slot free";
    const title = document.createElement("h3");
    title.textContent = slot.name;
    card.append(title);
    return card;
  });
  document.querySelector("#slot-grid").replaceChildren(...cards);
}
```

Use `textContent` for every API-derived value. Do not access `rfid_uid` or `active_session_id`. Fetch all four APIs concurrently, update only after the complete refresh succeeds, preserve the last good state on failure, and poll on a fixed interval. Render selected optimizer/predictor, actual forecast model and fallback, target timestamp, occupancy summary, and both comparison tables.

- [ ] **Step 4: Verify GREEN and inspect in a browser**

Run: `/home/xtrmn8/smart-parking/.venv/bin/python -m pytest tests/test_dashboard.py -v`

Start the app against a temporary demo database. Use Playwright CLI to open `/dashboard`, wait for `[data-slot-id]`, compare the card count with `/api/parking/status`, and confirm page text excludes the private RFID fixture.

- [ ] **Step 5: Commit**

```bash
git add backend/app/static tests/test_dashboard.py
git commit -m "feat: render live parking dashboard"
```

### Task 3: Simulated end-to-end HTTP client

**Files:**
- Create: `scripts/run_simulated_demo.py`
- Create: `tests/test_simulated_demo.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `--base-url`, `--rfid-uid`, `--idempotency-key`; existing entry, status, allocation-run, and prediction APIs.
- Produces: exit code zero and an RFID-free JSON summary containing camera result, entry slot, optimizer comparison, prediction, and final occupancy counts.

- [ ] **Step 1: Write a failing request-sequence and privacy test**

```python
def test_demo_calls_existing_apis_and_redacts_rfid(simulated_server, capsys) -> None:
    result = main([
        "--base-url", simulated_server.base_url,
        "--rfid-uid", "CARD-PRIVATE",
        "--idempotency-key", "demo-entry-1",
    ])
    output = capsys.readouterr().out
    assert result == 0
    assert simulated_server.paths == [
        "/api/camera/occupancy", "/api/vehicle/entry", "/api/parking/status",
        "/api/allocation/run", "/api/prediction", "/api/parking/status",
    ]
    assert "CARD-PRIVATE" not in output
```

This catches bypassing a public contract, an incomplete demo sequence, or leaking RFID through output.

- [ ] **Step 2: Verify RED**

Run: `/home/xtrmn8/smart-parking/.venv/bin/python -m pytest tests/test_simulated_demo.py -v`

Expected: FAIL because `scripts.run_simulated_demo` does not exist.

- [ ] **Step 3: Implement the standard-library client**

```python
def request_json(base_url: str, path: str, *, payload: object | None = None) -> object:
    data = None if payload is None else json.dumps(payload).encode()
    request = Request(f"{base_url.rstrip('/')}{path}", data=data)
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    with urlopen(request, timeout=10) as response:
        return json.load(response)
```

Generate a deterministic 1280x720 JPEG with Pillow, encode one multipart request,
post it to the camera endpoint, post entry, get status, derive a valid allocation
comparison request from every returned slot, post `algorithm: all`, get
prediction, and get final status. Build output only from camera outcome counts,
slot name/ID, benchmark metrics, forecast values, and occupancy counts.

- [ ] **Step 4: Verify GREEN**

Run: `/home/xtrmn8/smart-parking/.venv/bin/python -m pytest tests/test_simulated_demo.py -v`

Expected: PASS.

- [ ] **Step 5: Document and commit**

Document seeding prediction history with `scripts.seed_prediction_demo_data`,
running `make run`, opening `/dashboard`, then invoking
`python -m scripts.run_simulated_demo` from another terminal.

```bash
git add scripts/run_simulated_demo.py tests/test_simulated_demo.py README.md
git commit -m "feat: add simulated dashboard demo"
```

### Task 4: Verification evidence and branch completion

**Files:**
- Modify: `progress.md`

**Interfaces:**
- Consumes: final code and fresh verification output.
- Produces: accurate milestone status and handoff evidence.

- [ ] **Step 1: Run focused tests**

Run: `/home/xtrmn8/smart-parking/.venv/bin/python -m pytest tests/test_dashboard.py tests/test_simulated_demo.py -v`

- [ ] **Step 2: Run full verification**

```bash
/home/xtrmn8/smart-parking/.venv/bin/python -m pytest
/home/xtrmn8/smart-parking/.venv/bin/python -m ruff check .
git diff --check
```

- [ ] **Step 3: Update progress from fresh output**

Record the exact focused/full pass and skip counts, known warnings, branch, latest relevant commit, and next task. Mark Dashboard and End-to-end demo complete only if their acceptance coverage is green.

- [ ] **Step 4: Commit progress documentation**

```bash
git add progress.md
git diff --cached --check
git diff --cached --stat
git commit -m "docs: record dashboard verification"
```

- [ ] **Step 5: Finish the feature branch**

Invoke `superpowers:verification-before-completion`, then `superpowers:finishing-a-development-branch`. Present the required integration options. Merge into `main` locally only after the user selects that option; never push.
