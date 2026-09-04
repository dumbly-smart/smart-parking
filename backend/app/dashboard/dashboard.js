"use strict";

const elements = {
  connection: document.querySelector("#connection-status"),
  refreshTime: document.querySelector("#last-refresh"),
  total: document.querySelector("#total-count"),
  available: document.querySelector("#available-count"),
  occupied: document.querySelector("#occupied-count"),
  active: document.querySelector("#active-count"),
  parkingGrid: document.querySelector("#parking-grid"),
  form: document.querySelector("#rfid-form"),
  uid: document.querySelector("#rfid-uid"),
  entryButton: document.querySelector("#entry-button"),
  exitButton: document.querySelector("#exit-button"),
  assignment: document.querySelector("#latest-assignment"),
  activity: document.querySelector("#activity-list"),
  benchmarks: document.querySelector("#benchmark-body"),
  announcement: document.querySelector("#announcement"),
};

const messages = {
  no_available_slot: "The facility is full. No parking bay is available.",
  vehicle_already_parked: "This vehicle already has an active parking session.",
  vehicle_not_parked: "This vehicle does not have an active parking session.",
  idempotency_conflict: "This operation conflicts with a previous request.",
};

let isRefreshing = false;
let isOffline = false;

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

async function apiRequest(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) {
    const detail = payload.detail || {};
    const error = new Error(messages[detail.code] || detail.message || "Request failed.");
    error.code = detail.code || `http_${response.status}`;
    throw error;
  }
  return payload;
}

function setConnection(online) {
  const label = elements.connection.querySelector(".connection__label");
  elements.connection.classList.remove(
    "status--connecting",
    "status--online",
    "status--offline",
  );
  elements.connection.classList.add(online ? "status--online" : "status--offline");
  label.textContent = online ? "Live" : "Offline";
}

function renderStatus(payload) {
  const slots = payload.slots || [];
  const occupied = slots.filter((slot) => slot.occupied).length;
  const active = slots.filter((slot) => slot.active_session_id !== null).length;
  elements.total.textContent = String(slots.length);
  elements.available.textContent = String(slots.length - occupied);
  elements.occupied.textContent = String(occupied);
  elements.active.textContent = String(active);

  const cards = slots.map((slot) => {
    const card = node("article", `slot slot--${slot.occupied ? "occupied" : "free"}`);
    card.dataset.slotId = String(slot.id);

    const top = node("div", "slot__top");
    top.append(
      node("span", "slot__number", `BAY ${String(slot.id).padStart(2, "0")}`),
      node("span", "slot__status", slot.occupied ? "● Occupied" : "● Free"),
    );

    const name = node("strong", "slot__name", slot.name);
    const vehicle = node(
      "span",
      "slot__vehicle",
      slot.rfid_uid ? `RFID / ${slot.rfid_uid}` : "Ready for allocation",
    );
    const meta = node("div", "slot__meta");
    const zone = node("span");
    zone.append("Zone ", node("b", "", slot.zone));
    const distance = node("span");
    distance.append("Walk ", node("b", "", `${Math.round(slot.walking_distance * 100)}%`));
    meta.append(zone, distance);
    card.append(top, name, vehicle, meta);
    return card;
  });
  elements.parkingGrid.replaceChildren(...cards);
}

function detail(label, value) {
  const wrapper = node("div", "detail");
  wrapper.append(node("span", "", label), node("strong", "", value));
  return wrapper;
}

function renderAssignment(payload) {
  const wrapper = node("div", "assignment");
  const slot = node("div", "assignment__slot");
  slot.append(node("small", "", "Assigned bay"), node("strong", "", payload.slot_name));
  const details = node("div", "assignment__details");
  details.append(
    detail("RFID", payload.rfid_uid),
    detail("Optimizer", payload.optimizer.toUpperCase()),
    detail("Allocation cost", Number(payload.allocation_cost).toFixed(3)),
    detail("Gate action", payload.gate_action.toUpperCase()),
  );
  wrapper.append(slot, details);
  elements.assignment.className = "assignment-host";
  elements.assignment.replaceChildren(wrapper);
}

function renderDeparture(payload) {
  const wrapper = node("div", "assignment");
  const slot = node("div", "assignment__slot");
  slot.append(node("small", "", "Released bay"), node("strong", "", payload.slot_name));
  const details = node("div", "assignment__details");
  details.append(
    detail("RFID", payload.rfid_uid),
    detail("Session", `#${payload.session_id}`),
    detail("Status", "DEPARTED"),
    detail("Gate action", payload.gate_action.toUpperCase()),
  );
  wrapper.append(slot, details);
  elements.assignment.className = "assignment-host";
  elements.assignment.replaceChildren(wrapper);
}

function renderBenchmarks(payload) {
  const runs = (payload.runs || []).slice(0, 10);
  if (!runs.length) {
    const row = node("tr");
    const cell = node("td", "", "No allocation runs yet. Simulate an entry to begin.");
    cell.colSpan = 4;
    row.append(cell);
    elements.benchmarks.replaceChildren(row);
    return;
  }
  const rows = runs.map((run) => {
    const row = node("tr");
    row.append(
      node("td", "", run.algorithm),
      node("td", "", run.chosen_slot_id ? `S${run.chosen_slot_id}` : "—"),
      node("td", "", run.best_cost === null ? "—" : Number(run.best_cost).toFixed(3)),
      node("td", "", `${Number(run.runtime_ms).toFixed(2)} ms`),
    );
    return row;
  });
  elements.benchmarks.replaceChildren(...rows);
}

function addActivity(kind, title, description) {
  const item = node("li", `activity activity--${kind}`);
  item.append(node("span", "activity__mark"));
  const copy = node("div");
  copy.append(node("strong", "", title), node("small", "", description));
  const timestamp = node("time", "", new Date().toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  }));
  item.append(copy, timestamp);
  elements.activity.prepend(item);
  while (elements.activity.children.length > 6) elements.activity.lastElementChild.remove();
  elements.announcement.textContent = `${title}. ${description}`;
}

function operationKey(operation) {
  const randomPart = typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2);
  return `${operation}-${Date.now()}-${randomPart}`;
}

function setBusy(busy) {
  elements.entryButton.disabled = busy;
  elements.exitButton.disabled = busy;
}

async function submitVehicleOperation(operation) {
  const rfidUid = elements.uid.value.trim().toUpperCase();
  elements.uid.value = rfidUid;
  if (!rfidUid) {
    const message = "Enter an RFID identifier before simulating access.";
    addActivity("error", "RFID required", message);
    elements.uid.focus();
    return;
  }

  setBusy(true);
  try {
    const payload = await apiRequest(`/api/vehicle/${operation}`, {
      method: "POST",
      body: JSON.stringify({ rfid_uid: rfidUid, idempotency_key: operationKey(operation) }),
    });
    if (operation === "entry") {
      renderAssignment(payload);
      addActivity("success", "Vehicle admitted", `${rfidUid} assigned to ${payload.slot_name}`);
    } else {
      renderDeparture(payload);
      addActivity("success", "Vehicle departed", `${rfidUid} released ${payload.slot_name}`);
    }
    await refreshDashboard();
  } catch (error) {
    addActivity("error", "Access request denied", error.message);
  } finally {
    setBusy(false);
  }
}

async function refreshDashboard() {
  if (isRefreshing) return;
  isRefreshing = true;
  try {
    const [status, benchmarks] = await Promise.all([
      apiRequest("/api/parking/status"),
      apiRequest("/api/benchmarks/optimizers"),
    ]);
    renderStatus(status);
    renderBenchmarks(benchmarks);
    setConnection(true);
    elements.refreshTime.textContent = new Date().toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
    if (isOffline) addActivity("success", "Connection restored", "Live facility data resumed");
    isOffline = false;
  } catch (error) {
    setConnection(false);
    if (!isOffline) addActivity("error", "Backend offline", error.message);
    isOffline = true;
  } finally {
    isRefreshing = false;
  }
}

elements.form.addEventListener("submit", (event) => {
  event.preventDefault();
  const operation = event.submitter?.dataset.operation;
  if (operation === "entry" || operation === "exit") submitVehicleOperation(operation);
});

refreshDashboard();
setInterval(refreshDashboard, 2000);
