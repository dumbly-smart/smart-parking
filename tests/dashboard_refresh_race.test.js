"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

class FakeElement {
  constructor() {
    this.children = [];
    this.classList = { add() {}, remove() {} };
    this.dataset = {};
    this.value = "";
  }

  append(...children) { this.children.push(...children); }
  prepend(child) { this.children.unshift(child); }
  replaceChildren(...children) { this.children = children; }
  addEventListener() {}
  focus() {}
  select() {}
  remove() {}
  querySelector() { return new FakeElement(); }

  get lastElementChild() { return this.children.at(-1) || null; }
}

const elements = new Map();
const requests = [];
const document = {
  createElement: () => new FakeElement(),
  querySelector(selector) {
    if (!elements.has(selector)) elements.set(selector, new FakeElement());
    return elements.get(selector);
  },
};

function fetch(path) {
  return new Promise((resolve) => requests.push({ path, resolve }));
}

function respond(request, payload) {
  request.resolve({ ok: true, json: async () => payload });
}

function flushPromises() {
  return new Promise((resolve) => setImmediate(resolve));
}

async function main() {
  const context = vm.createContext({
    console,
    crypto: { randomUUID: () => "test-uuid" },
    document,
    fetch,
    setInterval() {},
  });
  const script = fs.readFileSync("backend/app/dashboard/dashboard.js", "utf8");
  vm.runInContext(script, context);

  assert.equal(requests.length, 2, "initial dashboard refresh should start two requests");
  const operationRefresh = vm.runInContext("refreshAfterOperation()", context);
  assert.equal(requests.length, 2, "operation refresh must wait for the active poll");

  respond(requests[0], { slots: [] });
  await flushPromises();
  assert.equal(requests.length, 2, "one unfinished poll request must keep the refresh queued");

  respond(requests[1], { runs: [] });
  await flushPromises();
  assert.equal(requests.length, 4, "operation refresh must fetch fresh state after the poll");
  assert.deepEqual(
    requests.slice(2).map((request) => request.path),
    ["/api/parking/status", "/api/benchmarks/optimizers"],
  );

  respond(requests[2], { slots: [] });
  respond(requests[3], { runs: [] });
  await operationRefresh;
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
