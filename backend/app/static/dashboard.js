"use strict";

const bootstrap = JSON.parse(document.querySelector("#dashboard-bootstrap").textContent);
const refreshIntervalMs = 10_000;

function text(selector, value) {
  document.querySelector(selector).textContent = value;
}

function formattedTimestamp(value) {
  return new Date(value).toLocaleString();
}

function decimal(value, digits = 3) {
  return Number(value).toFixed(digits);
}

function percentage(value) {
  return `${Math.round(Number(value) * 100)}%`;
}

function cell(value) {
  const item = document.createElement("td");
  item.textContent = value;
  return item;
}

function renderSlots(slots) {
  const cards = slots.map((slot) => {
    const card = document.createElement("article");
    const heading = document.createElement("h3");
    const zone = document.createElement("p");
    const state = document.createElement("p");
    const updated = document.createElement("p");
    card.className = slot.occupied ? "slot occupied" : "slot free";
    card.dataset.slotId = String(slot.id);
    heading.textContent = slot.name;
    zone.textContent = `Zone: ${slot.zone}`;
    state.className = "slot-state";
    state.textContent = slot.occupied ? "Occupied" : "Free";
    updated.textContent = `Updated: ${formattedTimestamp(slot.updated_at)}`;
    card.append(heading, zone, state, updated);
    return card;
  });
  document.querySelector("#slot-grid").replaceChildren(...cards);
}

function renderOptimizerRuns(runs) {
  const rows = runs.slice(0, 12).map((run) => {
    const row = document.createElement("tr");
    row.append(
      cell(run.algorithm.toUpperCase()),
      cell(String(run.chosen_slot_id)),
      cell(decimal(run.best_cost)),
      cell(String(run.iterations)),
      cell(`${decimal(run.runtime_ms)} ms`),
    );
    return row;
  });
  document.querySelector("#optimizer-runs").replaceChildren(...rows);
  document.querySelector("#optimizer-empty").hidden = runs.length !== 0;
}

function renderPredictorRuns(runs) {
  const rows = runs.slice(0, 12).map((run) => {
    const row = document.createElement("tr");
    row.append(
      cell(run.model.toUpperCase()),
      cell(decimal(run.mae)),
      cell(decimal(run.mse)),
      cell(decimal(run.rmse)),
      cell(`${decimal(run.inference_latency_ms)} ms`),
    );
    return row;
  });
  document.querySelector("#predictor-runs").replaceChildren(...rows);
  document.querySelector("#predictor-empty").hidden = runs.length !== 0;
}

function renderDashboard(status, optimizers, predictors, prediction) {
  const occupied = status.slots.filter((slot) => slot.occupied).length;
  text("#selected-optimizer", bootstrap.selected_optimizer);
  text("#selected-predictor", bootstrap.selected_predictor);
  text("#occupancy-summary", `${occupied} / ${status.slots.length}`);
  text("#forecast-model", prediction.model);
  text("#forecast-occupancy", percentage(prediction.occupancy_ratio));
  text("#forecast-target", formattedTimestamp(prediction.target_at));
  text("#forecast-fallback", prediction.fallback_reason || "Model prediction available");
  renderSlots(status.slots);
  renderOptimizerRuns(optimizers.runs);
  renderPredictorRuns(predictors.runs);
}

async function fetchJson(path) {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  return response.json();
}

async function refresh() {
  const error = document.querySelector("#dashboard-error");
  try {
    const [status, optimizers, predictors, prediction] = await Promise.all([
      fetchJson("/api/parking/status"),
      fetchJson("/api/benchmarks/optimizers"),
      fetchJson("/api/benchmarks/predictors"),
      fetchJson("/api/prediction"),
    ]);
    renderDashboard(status, optimizers, predictors, prediction);
    error.hidden = true;
    text("#refresh-status", `Updated ${new Date().toLocaleTimeString()}`);
  } catch (exception) {
    error.textContent = "Live data is temporarily unavailable. Showing the last successful update.";
    error.hidden = false;
    text("#refresh-status", "Refresh failed");
  }
}

refresh();
window.setInterval(refresh, refreshIntervalMs);
