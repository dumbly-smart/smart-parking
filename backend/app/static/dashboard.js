"use strict";

const bootstrap = JSON.parse(document.querySelector("#dashboard-bootstrap").textContent);
const statusRefreshIntervalMs = 1_500;
const insightsRefreshIntervalMs = 10_000;
let currentSlots = [];
let selectedSlotId = null;
let parkingScene = null;
let operationInProgress = false;
let statusInFlight = null;
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
  details.append(label, document.createTextNode(`  —  ${slot.zone} zone · ${slot.occupied && slot.rfid_uid ? `Vehicle ${slot.rfid_uid}` : "Ready for the next vehicle"} · Updated ${formattedTimestamp(slot.updated_at)}`));
  if (slot.occupied && slot.rfid_uid) document.querySelector("#vehicle-uid").value = slot.rfid_uid;
}

function renderSlots(slots) {
  const unchanged = currentSlots.length === slots.length && slots.every((slot, index) => {
    const old = currentSlots[index];
    return old.id === slot.id && old.name === slot.name && old.zone === slot.zone && old.occupied === slot.occupied && old.updated_at === slot.updated_at && old.active_session_id === slot.active_session_id && old.rfid_uid === slot.rfid_uid;
  });
  if (unchanged) return Promise.resolve();
  const previous = new Map(currentSlots.map((slot) => [slot.id, slot]));
  const changes = slots.filter((slot) => {
    const old = previous.get(slot.id);
    return old && (old.occupied !== slot.occupied || (slot.occupied && old.active_session_id !== slot.active_session_id));
  });
  currentSlots = slots;
  const cards = slots.map((slot) => {
    const card = document.createElement("button");
    card.type = "button";
    card.className = `slot ${slot.occupied ? "occupied" : "free"}${selectedSlotId === slot.id ? " selected" : ""}`;
    card.dataset.slotId = String(slot.id);
    const top = document.createElement("div"); top.className = "slot-top";
    const name = document.createElement("h3"); name.textContent = slot.name;
    const state = document.createElement("span"); state.className = "slot-state"; state.textContent = slot.occupied ? "● Occupied" : "● Available";
    top.append(name, state);
    const zone = document.createElement("p"); zone.className = "slot-zone"; zone.textContent = `${slot.zone} zone`;
    const vehicle = document.createElement("p"); vehicle.className = "slot-vehicle"; vehicle.textContent = slot.occupied ? (slot.rfid_uid || "Vehicle detected") : "Open space";
    card.append(top, zone, vehicle);
    card.addEventListener("click", () => { selectSlot(slot.id); parkingScene?.focusSlot(slot.id); });
    return card;
  });
  document.querySelector("#slot-grid").replaceChildren(...cards);
  if (changes.length && !operationInProgress) {
    const latest = changes.at(-1);
    const vehicle = latest.rfid_uid || "Vehicle";
    setMessage(latest.occupied ? `Live arrival: ${vehicle} assigned to ${latest.name}.` : `Live departure from ${latest.name}.`, "success");
  }
  if (selectedSlotId !== null) selectSlot(selectedSlotId);
  return parkingScene?.syncSlots(slots, { animate: !eventStreamActive }) || Promise.resolve();
}

function renderOptimizerRuns(runs) {
  const rows = runs.slice(0, 12).map((run) => { const row = document.createElement("tr"); row.append(cell(run.algorithm.toUpperCase()), cell(String(run.chosen_slot_id)), cell(decimal(run.best_cost)), cell(String(run.iterations)), cell(`${decimal(run.runtime_ms)} ms`)); return row; });
  document.querySelector("#optimizer-runs").replaceChildren(...rows);
  document.querySelector("#optimizer-empty").hidden = runs.length !== 0;
}
function renderPredictorRuns(runs) {
  const rows = runs.slice(0, 12).map((run) => { const row = document.createElement("tr"); row.append(cell(run.model.toUpperCase()), cell(decimal(run.mae)), cell(decimal(run.mse)), cell(decimal(run.rmse)), cell(`${decimal(run.inference_latency_ms)} ms`)); return row; });
  document.querySelector("#predictor-runs").replaceChildren(...rows);
  document.querySelector("#predictor-empty").hidden = runs.length !== 0;
}
function renderStatus(status) {
  const occupied = status.slots.filter((slot) => slot.occupied).length;
  const total = status.slots.length;
  text("#occupancy-count", occupied);
  text("#occupancy-total", `/ ${total}`);
  text("#available-count", total - occupied);
  text("#occupancy-rate", `${Math.round(occupied / total * 100)}%`);
  text("#space-count", total);
  document.querySelector("#occupancy-progress").style.width = `${occupied / total * 100}%`;
  return renderSlots(status.slots);
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
    if (event.source === "controller") pendingHardwareMotion.set(event.operation_key, { operation, slot_id: event.slot_id });
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
    if (event.event_type === "rfid_read") setMessage(`RFID detected: ${event.rfid_uid}. Waiting for assignment…`);
    if (event.event_type === "slot_assigned") setMessage(`${event.rfid_uid} assigned to space ${event.slot_id}.`, "success");
    if (event.event_type === "vehicle_exited") setMessage(`${event.rfid_uid} departed from space ${event.slot_id}.`, "success");
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
    const result = await fetchJson(`/api/vehicle/${operation}`, { method: "POST", body: JSON.stringify({ rfid_uid: uid, idempotency_key: `${operation}-${crypto.randomUUID()}`, source: "simulation" }) });
    selectSlot(result.slot_id);
    setMessage(operation === "entry" ? `${uid} assigned to ${result.slot_name}. Driving to the space…` : `${uid} departing from ${result.slot_name}…`, "success");
    const { motion, error } = await refreshStatus({ fresh: true });
    if (error) throw error;
    if (parkingScene) {
      parkingScene.resetView();
      await motion;
      if (operation === "entry") parkingScene.focusSlot(result.slot_id);
    }
    setMessage(operation === "entry" ? `${uid} parked in ${result.slot_name}.` : `${uid} exited from ${result.slot_name}.`, "success");
    await refreshStatus({ fresh: true });
  } catch (exception) { setMessage(String(exception.message || exception), "error"); }
  finally { operationInProgress = false; document.querySelector("#entry-button").disabled = false; document.querySelector("#exit-button").disabled = false; }
}

document.querySelector("#entry-button").addEventListener("click", () => simulate("entry"));
document.querySelector("#exit-button").addEventListener("click", () => simulate("exit"));
document.querySelector("#vehicle-uid").addEventListener("keydown", (event) => { if (event.key === "Enter") simulate("entry"); });
document.querySelector("#reset-view").addEventListener("click", () => parkingScene?.resetView());

refreshStatus();
refreshInsights();
window.setInterval(refreshStatus, statusRefreshIntervalMs);
window.setInterval(refreshInsights, insightsRefreshIntervalMs);
document.addEventListener("visibilitychange", () => { if (!document.hidden) refreshStatus({ fresh: true }); });
import("/static/parking-scene.js?v=8").then(async ({ createParkingScene }) => {
  parkingScene = await createParkingScene(document.querySelector("#parking-scene"), (slotId) => { selectSlot(slotId); parkingScene?.focusSlot(slotId); }, bootstrap.scene);
  parkingScene.syncSlots(currentSlots, { animate: false });
  for (const event of queuedSceneEvents) applySceneEvent(event);
  queuedSceneEvents.length = 0;
  if (selectedSlotId !== null) parkingScene.selectSlot(selectedSlotId);
  document.querySelector("#scene-loading").hidden = true;
}).catch(() => { document.querySelector("#scene-loading").textContent = "3D view unavailable. Live space cards remain active."; });
