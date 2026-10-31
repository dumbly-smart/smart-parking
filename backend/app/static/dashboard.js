"use strict";

const bootstrap = JSON.parse(document.querySelector("#dashboard-bootstrap").textContent);
const statusRefreshIntervalMs = 1_500;
const insightsRefreshIntervalMs = 10_000;
const sumoRefreshIntervalMs = 800;
const STORED_PREDICTOR_RESULTS = bootstrap.predictor_comparison;
let currentSlots = [];
let modeledBays = [];
let selectedSlotId = null;
let parkingScene = null;
let operationInProgress = false;
let statusInFlight = null;
let sumoInFlight = null;
let statusFailed = false;
let insightsFailed = false;
let eventSource = null;
let eventStreamActive = false;
const pendingHardwareMotion = new Map();
const queuedSceneEvents = [];

function text(selector, value) { document.querySelector(selector).textContent = value; }
function updateDataError() {
  const error = document.querySelector("#dashboard-error");
  error.hidden = !statusFailed && !insightsFailed;
  if (statusFailed) error.textContent = "Live data is temporarily unavailable. Showing the last successful update.";
  else if (insightsFailed) error.textContent = "Insights are temporarily unavailable. Showing the last successful update.";
}
function formattedTimestamp(value) { return value ? new Date(value).toLocaleString() : "—"; }
function decimal(value, digits = 3) { return Number(value).toFixed(digits); }
function percentage(value) { return `${Math.round(Number(value) * 100)}%`; }
function cell(value) { const item = document.createElement("td"); item.textContent = value; return item; }

function selectSlot(slotId) {
  selectedSlotId = slotId;
  const slot = currentSlots.find((item) => item.id === slotId);
  document.querySelectorAll(".slot").forEach((item) => item.classList.toggle("selected", Number(item.dataset.slotId) === slotId));
  parkingScene?.selectSlot(slotId);
  if (!slot) return;
  const details = document.querySelector("#selected-space");
  details.replaceChildren();
  const label = document.createElement("strong");
  label.textContent = `${slot.name} · ${slot.occupied ? "Occupied" : "Available"}`;
  details.append(label, document.createTextNode(`  —  ${slot.zone} zone · ${slot.occupied && slot.rfid_uid ? `Vehicle ${slot.rfid_uid} · Current fee ₹${((slot.amount_due_paise || 0) / 100).toFixed(2)}` : "Ready for the next vehicle"} · Updated ${formattedTimestamp(slot.updated_at)}`));
  if (slot.occupied && slot.rfid_uid) document.querySelector("#vehicle-uid").value = slot.rfid_uid;
}

function renderSlots(slots) {
  const unchanged = currentSlots.length === slots.length && slots.every((slot, index) => {
    const old = currentSlots[index];
    return old.id === slot.id && old.name === slot.name && old.zone === slot.zone && old.occupied === slot.occupied && old.updated_at === slot.updated_at && old.active_session_id === slot.active_session_id && old.rfid_uid === slot.rfid_uid && old.amount_due_paise === slot.amount_due_paise;
  });
  if (unchanged) return Promise.resolve();
  const previous = new Map(currentSlots.map((slot) => [slot.id, slot]));
  const changes = slots.filter((slot) => {
    const old = previous.get(slot.id);
    return old && (old.occupied !== slot.occupied || (slot.occupied && old.active_session_id !== slot.active_session_id));
  });
  currentSlots = slots;
  renderAllSpaces(slots);
  if (changes.length && !operationInProgress) {
    const latest = changes.at(-1);
    const vehicle = latest.rfid_uid || "Vehicle";
    setMessage(latest.occupied ? `Live arrival: ${vehicle} assigned to ${latest.name}.` : `Live departure from ${latest.name}.`, "success");
  }
  if (selectedSlotId !== null) selectSlot(selectedSlotId);
  return parkingScene?.syncSlots(slots, { animate: !eventStreamActive }) || Promise.resolve();
}

function renderAllSpaces(slots = currentSlots) {
  const liveById = new Map(slots.map((slot) => [slot.id, slot]));
  const floorFilter = document.querySelector("#space-floor-filter")?.value || "all";
  const query = (document.querySelector("#space-search")?.value || "").trim().toLowerCase();
  const all = modeledBays.map((bay) => ({ bay, live: liveById.get(bay.slot_id) || null }));
  const filtered = all.filter(({ bay, live }) => (floorFilter === "all" || String(bay.floor) === floorFilter) && (!query || `${bay.id} ${bay.zone} ${bay.floor_name} ${live?.name || ""}`.toLowerCase().includes(query)));
  const cards = filtered.map(({ bay, live }) => {
    const name = live?.name || bay.slot_name;
    const card = document.createElement("button");
    card.type = "button";
    card.className = `slot ${live?.occupied ? "occupied" : "free"}${selectedSlotId === live?.id ? " selected" : ""}`;
    card.dataset.slotId = String(bay.slot_id);
    const top = document.createElement("div"); top.className = "slot-top";
    const title = document.createElement("h3"); title.textContent = name;
    const state = document.createElement("span"); state.className = "slot-state"; state.textContent = live?.occupied ? "● Occupied" : "● Available";
    top.append(title, state);
    const zone = document.createElement("p"); zone.className = "slot-zone"; zone.textContent = `${bay.floor_name} · ${bay.zone} zone`;
    const detail = document.createElement("p"); detail.className = "slot-vehicle"; detail.textContent = live?.occupied ? (live.rfid_uid || "Vehicle detected") : "Open · live tracked";
    card.append(top, zone, detail);
    card.addEventListener("click", () => { selectSlot(bay.slot_id); parkingScene?.focusSlot(bay.slot_id); });
    return card;
  });
  document.querySelector("#slot-grid").replaceChildren(...cards);
  text("#space-count", `${filtered.length.toLocaleString()} / ${all.length.toLocaleString()}`);
  text("#space-summary", `${all.length.toLocaleString()} live tracked spaces across six floors`);
}

function renderStatus(status) {
  const occupied = status.slots.filter((slot) => slot.occupied).length;
  const total = status.slots.length;
  text("#occupancy-count", occupied.toLocaleString());
  text("#occupancy-total", `/ ${total}`);
  text("#available-count", total - occupied);
  text("#occupancy-rate", `${Math.round(occupied / total * 100)}% occupied`);
  document.querySelector("#occupancy-progress").style.width = `${occupied / total * 100}%`;
  return renderSlots(status.slots);
}

function renderOptimizerRuns(runs) {
  const rows = runs.slice(0, 12).map((run) => { const row = document.createElement("tr"); row.append(cell(run.algorithm.toUpperCase()), cell(String(run.chosen_slot_id)), cell(decimal(run.best_cost)), cell(String(run.iterations)), cell(`${decimal(run.runtime_ms)} ms`)); return row; });
  document.querySelector("#optimizer-runs").replaceChildren(...rows);
  document.querySelector("#optimizer-empty").hidden = runs.length !== 0;
}
async function compareOptimizers() {
  const button = document.querySelector("#run-optimizer-comparison");
  const status = document.querySelector("#optimizer-comparison-status");
  if (!currentSlots.length) { status.textContent = "Waiting for live slot data."; return; }
  button.disabled = true; status.textContent = "Running GA, PSO, ACO, and NSGA-II on the current garage state…";
  const zoneTotals = new Map(), zoneOccupied = new Map();
  for (const slot of currentSlots) { zoneTotals.set(slot.zone, (zoneTotals.get(slot.zone) || 0) + 1); if (slot.occupied) zoneOccupied.set(slot.zone, (zoneOccupied.get(slot.zone) || 0) + 1); }
  const candidates = currentSlots.map((slot) => ({slot_id: slot.id, occupied: slot.occupied, distance: slot.walking_distance, congestion: (zoneOccupied.get(slot.zone) || 0) / zoneTotals.get(slot.zone), waiting: 0, fairness: 0}));
  try {
    const result = await fetchJson("/api/allocation/run", {method:"POST", body:JSON.stringify({algorithm:"all", request:{scenario_id:`dashboard-${Date.now()}`, candidates, seed:Math.floor(Math.random()*2147483647), iterations:30, population_size:48, generations:60, crossover_probability:.9, mutation_probability:.12}})});
    renderOptimizerRuns(result.results); status.textContent = `Compared ${result.results.length} algorithms against ${candidates.length.toLocaleString()} live bays.`;
  } catch (error) { status.textContent = `Comparison failed: ${error.message}`; }
  finally { button.disabled = false; }
}
function renderPredictorRuns(runs) {
  const usingStoredResults = runs.length === 0;
  const comparison = usingStoredResults ? STORED_PREDICTOR_RESULTS : runs;
  const rows = comparison.slice(0, 12).map((run) => {
    const row = document.createElement("tr");
    const model = run.model === "persistence_baseline" ? "Persistence baseline" : run.model.toUpperCase();
    row.append(cell(model), cell(decimal(run.mae, 6)), cell(decimal(run.mse, 6)), cell(decimal(run.rmse, 6)), cell(`${decimal(run.inference_latency_ms, 6)} ms`));
    return row;
  });
  document.querySelector("#predictor-runs").replaceChildren(...rows);
  document.querySelector("#predictor-empty").hidden = comparison.length !== 0;
  document.querySelector("#predictor-source").textContent = usingStoredResults ? "ACTUAL TEST RESULTS" : "SAVED BENCHMARK RUNS";
  const provenance = document.querySelector("#predictor-provenance");
  provenance.textContent = usingStoredResults
    ? "Actual saved held-out test metrics on the project’s synthetic dataset: 4,032 five-minute buckets, chronological 70/15/15 split. Latency is server-side inference, not ESP32 or hardware performance. Lower is better for every metric."
    : "Saved predictor benchmark runs. Latency is measured on the server; these values do not represent ESP32 or hardware inference.";
  provenance.hidden = false;
}
function renderInsights(optimizers, predictors, prediction) {
  text("#selected-optimizer", bootstrap.selected_optimizer);
  text("#selected-predictor", bootstrap.selected_predictor);
  text("#forecast-model", prediction.model);
  text("#forecast-occupancy", percentage(prediction.occupancy_ratio));
  document.querySelector("#forecast-progress").style.width = percentage(prediction.occupancy_ratio);
  text("#forecast-target", formattedTimestamp(prediction.target_at));
  text("#forecast-fallback", prediction.fallback_reason || "Model prediction available");
  renderOptimizerRuns(optimizers.runs);
  renderPredictorRuns(predictors.runs);
}
async function fetchJson(path, options = {}) {
  const response = await fetch(path, { headers: { Accept: "application/json", ...(options.body ? { "Content-Type": "application/json" } : {}) }, ...options });
  const data = await response.json();
  if (!response.ok) throw new Error(data?.detail?.message || data?.detail || `${path} returned ${response.status}`);
  return data;
}
function renderSumo(status) {
  const badge = document.querySelector("#sumo-badge");
  badge.className = `live-badge sumo-badge state-${status.state}`;
  const label = status.state === "running" ? "SUMO LIVE" : status.state === "paused" ? "SUMO PAUSED" : status.state === "error" ? "SUMO ERROR" : status.state === "unavailable" ? "SUMO OFFLINE" : `SUMO ${status.state.toUpperCase()}`;
  text("#sumo-state-label", label);
  document.querySelector("#sumo-stop").disabled = !["running", "paused"].includes(status.state);
  text("#sumo-vehicles", status.vehicle_count);
  text("#sumo-speed", (Number(status.mean_speed_mps || 0) * 3.6).toFixed(1));
  const seconds = Math.max(0, Math.floor(Number(status.simulation_time || 0)));
  text("#sumo-time", `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`);
  const message = document.querySelector("#sumo-message");
  message.textContent = status.error || (status.state === "running" ? "Traffic is moving through the city and garage. Parking arrivals, dwell and departures are tracked continuously." : status.state === "paused" ? "Simulation paused. Resume to continue garage traffic." : status.state === "stopped" ? "Start city traffic and all six garage levels." : status.state === "starting" ? "Connecting to the garage SUMO network…" : "SUMO needs its runtime and generated garage network. See the setup instructions.");
  message.classList.toggle("error", Boolean(status.error));
  document.querySelector("#sumo-start").disabled = ["running", "paused", "starting"].includes(status.state);
  document.querySelector("#sumo-pause").disabled = status.state !== "running";
  document.querySelector("#sumo-resume").disabled = status.state !== "paused";
  document.querySelector("#sumo-reset").disabled = status.state === "starting";
  parkingScene?.setTrafficSnapshot(status);
}
async function refreshSumo() {
  if (sumoInFlight) return sumoInFlight;
  const request = fetchJson("/api/sumo/status").then(renderSumo).catch((error) => {
    const message = document.querySelector("#sumo-message");
    message.textContent = `SUMO status unavailable: ${error.message}`;
    message.classList.add("error");
  }).finally(() => { if (sumoInFlight === request) sumoInFlight = null; });
  sumoInFlight = request;
  return request;
}
async function controlSumo(action) {
  const buttons = ["#sumo-start", "#sumo-stop", "#sumo-pause", "#sumo-resume", "#sumo-reset"].map((selector) => document.querySelector(selector));
  buttons.forEach((button) => { button.disabled = true; });
  try {
    const status = await fetchJson(`/api/sumo/${action}`, { method: "POST" });
    renderSumo(status);
  } catch (error) {
    const message = document.querySelector("#sumo-message");
    message.textContent = error.message;
    message.classList.add("error");
  } finally { refreshSumo(); }
}
async function refreshStatus({ fresh = false } = {}) {
  if (statusInFlight) {
    if (!fresh) return statusInFlight;
    try { await statusInFlight; } catch { /* Retry after a failed in-flight request. */ }
  }
  const request = (async () => {
    const status = await fetchJson("/api/parking/status");
    const motion = renderStatus(status);
    if (!eventSource) connectEvents(status.event_cursor || 0);
    statusFailed = false;
    updateDataError();
    text("#refresh-status", `Updated ${new Date().toLocaleTimeString()}`);
    return { motion };
  })();
  statusInFlight = request;
  try { return await request; }
  catch (exception) {
    statusFailed = true;
    updateDataError();
    text("#refresh-status", "Refresh failed");
    return { motion: Promise.resolve(), error: exception };
  } finally { if (statusInFlight === request) statusInFlight = null; }
}
async function refreshInsights() {
  try {
    const [optimizers, predictors, prediction] = await Promise.all([
      fetchJson("/api/benchmarks/optimizers"), fetchJson("/api/benchmarks/predictors"), fetchJson("/api/prediction"),
    ]);
    renderInsights(optimizers, predictors, prediction);
    insightsFailed = false;
    updateDataError();
  } catch (exception) {
    insightsFailed = true;
    updateDataError();
  }
}
function setMessage(message, kind = "") { const node = document.querySelector("#simulation-message"); node.textContent = message; node.className = `simulation-message ${kind}`; }
function showParkingReceipt(result, exiting) {
  let dialog = document.querySelector("#parking-receipt-dialog");
  if (!dialog) {
    dialog = document.createElement("dialog"); dialog.id = "parking-receipt-dialog";
    dialog.innerHTML = '<button class="receipt-close" aria-label="Close">×</button><h2>Parking receipt</h2><div class="receipt-content"></div><button class="receipt-navigate" type="button">Show route to this bay</button>';
    dialog.querySelector("button").onclick = () => dialog.close(); document.body.append(dialog);
    dialog.querySelector(".receipt-navigate").onclick = () => { const id = Number(dialog.dataset.slotId); dialog.close(); if (id && parkingScene) { parkingScene.followParking(id); document.querySelector("#garage-scene").scrollIntoView({behavior:"smooth",block:"center"}); } };
  }
  dialog.dataset.slotId = result.slot_id;
  dialog.querySelector(".receipt-navigate").hidden = exiting;
  const amount = exiting ? result.amount_paid_paise : result.amount_due_paise;
  const safe = (value) => String(value ?? "—").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));
  dialog.querySelector(".receipt-content").innerHTML = `<p><b>${exiting ? "PAID" : "PARKED · LIVE ESTIMATE"}</b></p><p>Vehicle ${safe(result.rfid_uid)} · Bay ${safe(result.slot_name)}</p><p>Entry ${safe(new Date(result.entered_at).toLocaleString())}</p>${exiting ? `<p>Exit ${safe(new Date(result.exited_at).toLocaleString())} · ${Math.floor(result.duration_seconds / 60)} minutes</p>` : ""}<p>₹50 first started hour, ₹40 each additional started hour · first 10 minutes free · ₹400 per 24 hours maximum</p><strong class="receipt-total">₹${(amount / 100).toFixed(2)}</strong><p><img width="180" height="180" alt="Scan to view full parking receipt" src="/api/parking/sessions/${result.session_id}/qr"></p><a target="_blank" href="${safe(result.receipt_url)}">Open full receipt</a>`;
  dialog.showModal();
}
function applySceneEvent(event) {
  if (!parkingScene) { queuedSceneEvents.push(event); return; }
  if (event.event_type === "gate_opened") {
    parkingScene.setGate(event.operation, true);
    const pending = pendingHardwareMotion.get(event.operation_key);
    if (pending) { parkingScene.animateEvent(pending.operation, pending.slot_id); pendingHardwareMotion.delete(event.operation_key); }
  } else if (event.event_type === "gate_closed") {
    parkingScene.setGate(event.operation, false);
  } else if (event.event_type === "slot_assigned" || event.event_type === "vehicle_exited") {
    const operation = event.operation;
    if (event.source === "controller") {pendingHardwareMotion.set(event.operation_key, { operation, slot_id: event.slot_id });parkingScene.followParking(event.slot_id);document.querySelector("#garage-scene").scrollIntoView({behavior:"smooth",block:"center"});}
    else { parkingScene.setGate(operation, null); parkingScene.animateEvent(operation, event.slot_id); }
  }
}
function connectEvents(cursor) {
  eventSource = new EventSource(`/api/parking/events/stream?since_id=${cursor}`);
  eventSource.onopen = () => { eventStreamActive = true; };
  eventSource.onerror = () => { eventStreamActive = false; };
  eventSource.addEventListener("parking", (message) => {
    const event = JSON.parse(message.data);
    applySceneEvent(event);
    if (event.event_type === "rfid_read") setMessage("RFID card detected. Waiting for assignment…");
    if (event.event_type === "slot_assigned") setMessage(`Space ${event.slot_id} assigned to the arriving vehicle.`, "success");
    if (event.event_type === "vehicle_exited") setMessage(`Vehicle departed from space ${event.slot_id}.`, "success");
    if (event.event_type === "slot_assigned" && event.session_id && event.source === "controller") fetchJson(`/api/parking/sessions/${event.session_id}`).then((receipt) => showParkingReceipt(receipt, false));
    refreshStatus({ fresh: true });
  });
}
async function simulate(operation) {
  if (operationInProgress) return;
  const uid = document.querySelector("#vehicle-uid").value.trim().toUpperCase();
  if (!uid) { setMessage("Enter a vehicle ID first, or select an occupied space to exit.", "error"); document.querySelector("#vehicle-uid").focus(); return; }
  operationInProgress = true;
  document.querySelector("#entry-button").disabled = true;
  document.querySelector("#exit-button").disabled = true;
  setMessage(operation === "entry" ? `Opening entry gate for ${uid}…` : `Opening exit gate for ${uid}…`);
  try {
    const result = await fetchJson(`/api/vehicle/${operation}`, { method: "POST", body: JSON.stringify({ rfid_uid: uid, idempotency_key: `${operation}-${crypto.randomUUID()}`, source: document.querySelector("#vehicle-input-mode").value === "rfid" ? "api" : "simulation" }) });
    showParkingReceipt(result, operation === "exit");
    selectSlot(result.slot_id);
    setMessage(operation === "entry" ? `${uid} assigned to ${result.slot_name}. Driving to the space…` : `${uid} departing from ${result.slot_name}…`, "success");
    const { motion, error } = await refreshStatus({ fresh: true });
    if (error) throw error;
    if (parkingScene) {
      parkingScene.followParking(result.slot_id);
      document.querySelector("#garage-scene").scrollIntoView({behavior:"smooth",block:"center"});
      await motion;
    }
    setMessage(operation === "entry" ? `${uid} assigned to ${result.slot_name}. Follow the route in the driver’s view.` : `${uid} exited from ${result.slot_name}.`, "success");
    await refreshStatus({ fresh: true });
  } catch (exception) { setMessage(String(exception.message || exception), "error"); }
  finally { operationInProgress = false; document.querySelector("#entry-button").disabled = false; document.querySelector("#exit-button").disabled = false; }
}

document.querySelector("#entry-button").addEventListener("click", () => simulate("entry"));
document.querySelector("#exit-button").addEventListener("click", () => simulate("exit"));
async function scanCard() {
  if(operationInProgress)return;
  const input=document.querySelector("#vehicle-uid"),uid=input.value.trim().toUpperCase();
  if(!uid){setMessage("Scan a card into the vehicle ID field, then press Enter.");input.focus();return;}
  const {error}=await refreshStatus({fresh:true});if(error)return;
  const occupied=currentSlots.some(slot=>slot.occupied && slot.rfid_uid===uid);
  await simulate(occupied ? "exit" : "entry");
}
document.querySelector("#scan-card").addEventListener("click",scanCard);
document.querySelector("#generate-vehicle").addEventListener("click",()=>{document.querySelector("#vehicle-uid").value=`DEMO-${crypto.randomUUID().slice(0,8).toUpperCase()}`;document.querySelector("#vehicle-uid").focus();});
document.querySelector("#vehicle-input-mode").addEventListener("change",event=>{const rfid=event.target.value==='rfid';document.querySelector("#vehicle-uid").placeholder=rfid?'Scan RFID card here, then Enter':'e.g. CAR-001';setMessage(rfid?'Keyboard readers: focus this field and scan. ESP32 RFID scans appear automatically.':'Generate or enter a vehicle ID, then park or release it.');document.querySelector("#vehicle-uid").focus();});
document.querySelector("#vehicle-uid").addEventListener("keydown",event=>{if(event.key==='Enter'){event.preventDefault();if(document.querySelector("#vehicle-input-mode").value==='rfid')scanCard();else simulate('entry');}});
document.querySelector("#reset-view").addEventListener("click", () => parkingScene?.resetView());
document.querySelector("#focus-live-bays").addEventListener("click", () => parkingScene?.focusLiveBays());
document.querySelector("#sumo-start").addEventListener("click", () => controlSumo("start"));
document.querySelector("#sumo-stop").addEventListener("click", () => controlSumo("stop"));
document.querySelector("#sumo-pause").addEventListener("click", () => controlSumo("pause"));
document.querySelector("#sumo-resume").addEventListener("click", () => controlSumo("resume"));
document.querySelector("#sumo-reset").addEventListener("click", () => controlSumo("reset"));

document.querySelector("#run-optimizer-comparison").addEventListener("click", compareOptimizers);
refreshStatus();
refreshInsights();
refreshSumo();
window.setInterval(refreshStatus, statusRefreshIntervalMs);
window.setInterval(refreshInsights, insightsRefreshIntervalMs);
window.setInterval(refreshSumo, sumoRefreshIntervalMs);
document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshStatus({ fresh: true }); });
document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshSumo(); });
Promise.all([import("/static/multi-floor-scene.js?v=24"), fetchJson("/api/sumo/map")]).then(async ([{ createParkingScene }, layout]) => {
  let nextSlotId = 6;
  modeledBays = layout.floors.flatMap(floor => floor.bays.map((bay, index) => {
    const slotId = bay.live_slot_id ?? nextSlotId++;
    return {...bay, slot_id:slotId, slot_name:bay.live_slot_id == null ? `L${floor.number}-${bay.zone}-${String(index+1).padStart(3,"0")}` : undefined, floor:floor.number, floor_name:floor.name};
  }));
  renderAllSpaces(currentSlots);
  parkingScene = await createParkingScene(document.querySelector("#garage-scene"), (slotId) => { selectSlot(slotId); parkingScene?.focusSlot(slotId); }, bootstrap.scene);
  parkingScene.setMapData(layout);
  parkingScene.syncSlots(currentSlots, { animate: false });
  for (const event of queuedSceneEvents) applySceneEvent(event);
  queuedSceneEvents.length = 0;
  if (selectedSlotId !== null) parkingScene.selectSlot(selectedSlotId);
  parkingScene.setTrafficSnapshot({ vehicles: [] });
  document.querySelector("#scene-loading").hidden = true;
}).catch((error) => { document.querySelector("#scene-loading").textContent = `Garage model unavailable: ${error.message}. Live space cards remain active.`; });
document.querySelector("#space-floor-filter").addEventListener("change", () => renderAllSpaces());
document.querySelector("#space-search").addEventListener("input", () => renderAllSpaces());
