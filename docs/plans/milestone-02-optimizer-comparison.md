# Optimizer Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver deterministic GA, PSO, and ACO allocation through one
normalized objective contract with persisted, API-visible comparisons.

**Architecture:** Immutable Pydantic domain schemas feed a pure objective
function and three optimizer implementations. A benchmark service gives each
optimizer the same request, while a SQLite repository and thin FastAPI routes
persist and expose results.

**Tech Stack:** Python 3.11+, Pydantic 2, standard-library `random`, SQLite,
FastAPI, pytest.

**Spec:** `2026-09-03-smart-parking-design.md`

## Global Constraints

- Version 1 supports exactly five slots.
- Default weights are distance 0.35, congestion 0.30, waiting 0.20, fairness
  0.15 and must sum to 1.0.
- Occupied slots are never assignable.
- Every test and benchmark accepts an explicit deterministic seed.
- Every result contains chosen slot, cost, iterations, runtime, and objective
  breakdown.

---

### Task 1: Objective and optimizer contracts

**Files:** Create `optimization/models.py`, `optimization/fitness.py`, and
`tests/test_optimization.py`.

**Interfaces:** Produce `SlotCandidate`, `AllocationRequest`,
`AllocationResult`, `ObjectiveBreakdown`, `Optimizer`, and
`weighted_cost(candidate, weights)`.

- [x] Write tests with literal expected weighted cost and validation failures
  for non-normalized values, duplicate/not-five slots, and invalid weights.
- [x] Run `.venv/bin/python -m pytest tests/test_optimization.py -q`; expect an
  import failure for `optimization.models`.
- [x] Implement frozen schemas, the optimizer protocol, and pure cost function.
- [x] Run the focused tests and confirm the contract tests pass.

### Task 2: Three deterministic optimizers

**Files:** Create `optimization/ga.py`, `optimization/pso.py`,
`optimization/aco.py`, and `optimization/common.py`; modify
`tests/test_optimization.py`.

**Interfaces:** Each class implements
`optimize(request: AllocationRequest) -> AllocationResult` and raises
`NoAvailableSlotError` for zero available candidates.

- [x] Add parametrized tests proving each algorithm excludes an objectively
  cheaper occupied slot, returns every required field, rejects full capacity,
  and repeats semantic results for a fixed seed.
- [x] Run the new cases and confirm missing optimizer imports fail.
- [x] Implement bounded discrete GA population evolution, PSO particle motion,
  and ACO pheromone sampling with per-call `random.Random(request.seed)`.
- [x] Run all optimizer tests and confirm they pass.

### Task 3: Benchmark persistence and API

**Files:** Create `optimization/benchmark.py` and `backend/app/routes/allocation.py`;
modify `backend/app/db.py`, `backend/app/main.py`, and
`tests/test_optimization.py`.

**Interfaces:** `BenchmarkRunner.run(request)` returns all three results;
`POST /api/allocation/run` accepts `{algorithm, request}` where algorithm may
be `ga`, `pso`, `aco`, or `all`; `GET /api/benchmarks/optimizers` returns
persisted runs newest first.

- [x] Add a real temporary-SQLite API test asserting three identical-scenario
  rows, result schemas, and no occupied assignment.
- [x] Run it and confirm 404 failure for the absent endpoint.
- [x] Add transactional repository methods, runner, route schemas, structured
  409 `no_available_slot` handling, and router registration.
- [x] Run focused and full suites plus Ruff, update ADR/progress/docs, inspect
  cached diff, commit, and push normally.
