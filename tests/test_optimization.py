from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.config import ObjectiveWeights, Settings
from backend.app.db import Database
from backend.app.main import create_app
from optimization.aco import AntColonyOptimizer
from optimization.fitness import weighted_cost
from optimization.ga import GeneticAlgorithmOptimizer
from optimization.models import (
    AllocationRequest,
    AllocationResult,
    NoAvailableSlotError,
    PersistedOptimizerRun,
    SlotCandidate,
)
from optimization.pso import ParticleSwarmOptimizer


def candidates(all_occupied: bool = False) -> list[SlotCandidate]:
    return [
        SlotCandidate(
            slot_id=1,
            occupied=True,
            distance=0.0,
            congestion=0.0,
            waiting=0.0,
            fairness=0.0,
        ),
        SlotCandidate(
            slot_id=2,
            occupied=all_occupied,
            distance=0.2,
            congestion=0.1,
            waiting=0.3,
            fairness=0.2,
        ),
        SlotCandidate(
            slot_id=3,
            occupied=all_occupied,
            distance=0.4,
            congestion=0.3,
            waiting=0.2,
            fairness=0.4,
        ),
        SlotCandidate(
            slot_id=4,
            occupied=all_occupied,
            distance=0.6,
            congestion=0.4,
            waiting=0.5,
            fairness=0.3,
        ),
        SlotCandidate(
            slot_id=5,
            occupied=all_occupied,
            distance=0.8,
            congestion=0.6,
            waiting=0.7,
            fairness=0.5,
        ),
    ]


def request(all_occupied: bool = False) -> AllocationRequest:
    return AllocationRequest(
        scenario_id="same-scenario",
        candidates=candidates(all_occupied),
        seed=17,
        iterations=12,
    )


def candidate(slot_id: int) -> SlotCandidate:
    return SlotCandidate(
        slot_id=slot_id,
        occupied=False,
        distance=0.2,
        congestion=0.2,
        waiting=0.2,
        fairness=0.2,
    )


def test_weighted_cost_uses_normalized_objectives_and_default_weights() -> None:
    candidate = SlotCandidate(
        slot_id=1,
        occupied=False,
        distance=0.2,
        congestion=0.4,
        waiting=0.6,
        fairness=0.8,
    )

    cost, breakdown = weighted_cost(candidate, ObjectiveWeights())

    assert cost == pytest.approx(0.43)
    assert breakdown.model_dump() == {
        "distance": 0.2,
        "congestion": 0.4,
        "waiting": 0.6,
        "fairness": 0.8,
    }


@pytest.mark.parametrize("field", ["distance", "congestion", "waiting", "fairness"])
def test_candidate_rejects_non_normalized_objectives(field: str) -> None:
    values = {
        "slot_id": 1,
        "occupied": False,
        "distance": 0.2,
        "congestion": 0.2,
        "waiting": 0.2,
        "fairness": 0.2,
    }
    values[field] = 1.01

    with pytest.raises(ValidationError):
        SlotCandidate.model_validate(values)


def test_allocation_request_accepts_dynamic_non_contiguous_candidates() -> None:
    allocation_request = AllocationRequest(
        scenario_id="dynamic",
        candidates=[candidate(2), candidate(9), candidate(21)],
    )

    assert isinstance(allocation_request.candidates, tuple)
    assert [item.slot_id for item in allocation_request.candidates] == [2, 9, 21]


@pytest.mark.parametrize("slot_ids", [[], [1, 1], [0]])
def test_allocation_request_rejects_empty_duplicate_or_non_positive_slot_ids(
    slot_ids: list[int],
) -> None:
    with pytest.raises(ValidationError):
        AllocationRequest(
            scenario_id="invalid",
            candidates=[candidate(slot_id) for slot_id in slot_ids],
        )


def test_allocation_result_accepts_any_positive_slot_id() -> None:
    result = AllocationResult(
        algorithm="ga",
        scenario_id="dynamic",
        chosen_slot_id=21,
        best_cost=0.2,
        iterations=1,
        runtime_ms=0.0,
        objective_breakdown={
            "distance": 0.2,
            "congestion": 0.2,
            "waiting": 0.2,
            "fairness": 0.2,
        },
        seed=42,
    )

    assert result.chosen_slot_id == 21


def test_allocation_request_is_deeply_immutable() -> None:
    allocation_request = request()

    with pytest.raises(ValidationError):
        allocation_request.weights.distance = 0.8


def test_allocation_result_is_immutable() -> None:
    result = GeneticAlgorithmOptimizer().optimize(request())

    with pytest.raises(ValidationError):
        result.chosen_slot_id = 5


@pytest.mark.parametrize(
    "optimizer",
    [GeneticAlgorithmOptimizer(), ParticleSwarmOptimizer(), AntColonyOptimizer()],
)
def test_optimizers_are_deterministic_and_never_choose_occupied_slot(optimizer: object) -> None:
    first = optimizer.optimize(request())  # type: ignore[attr-defined]
    second = optimizer.optimize(request())  # type: ignore[attr-defined]

    expected_costs = {2: 0.19, 3: 0.33, 4: 0.475, 5: 0.665}
    assert first.chosen_slot_id in expected_costs
    assert second.model_dump(exclude={"runtime_ms"}) == first.model_dump(
        exclude={"runtime_ms"}
    )
    assert first.best_cost == pytest.approx(expected_costs[first.chosen_slot_id])
    assert first.iterations == 12
    assert first.scenario_id == "same-scenario"
    assert first.runtime_ms >= 0
    assert first.objective_breakdown.distance > 0


@pytest.mark.parametrize(
    "optimizer",
    [GeneticAlgorithmOptimizer(), ParticleSwarmOptimizer(), AntColonyOptimizer()],
)
def test_optimizers_reject_when_every_slot_is_occupied(optimizer: object) -> None:
    with pytest.raises(NoAvailableSlotError):
        optimizer.optimize(request(all_occupied=True))  # type: ignore[attr-defined]


def test_one_iteration_runs_algorithm_search_instead_of_presolving() -> None:
    limited = request().model_copy(update={"seed": 0, "iterations": 1})

    assert GeneticAlgorithmOptimizer().optimize(limited).chosen_slot_id == 5
    assert ParticleSwarmOptimizer().optimize(limited).chosen_slot_id == 4
    assert AntColonyOptimizer().optimize(limited).chosen_slot_id == 2


def write_config(path: Path) -> None:
    path.write_text(
        """allocation:
  weights:
    distance: 0.35
    congestion: 0.30
    waiting: 0.20
    fairness: 0.15
slots:
  - {id: 1, name: S1, walking_distance: 0.2, zone: north}
  - {id: 2, name: S2, walking_distance: 0.3, zone: north}
  - {id: 3, name: S3, walking_distance: 0.5, zone: central}
  - {id: 4, name: S4, walking_distance: 0.7, zone: south}
  - {id: 5, name: S5, walking_distance: 0.9, zone: south}
""",
        encoding="utf-8",
    )


def test_benchmark_persistence_is_atomic(tmp_path: Path) -> None:
    config_path = tmp_path / "parking.yaml"
    write_config(config_path)
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'parking.db'}",
        parking_config_path=config_path,
    )
    database = Database(settings.database_path)
    database.initialize(settings.parking.slots)
    ga_result = GeneticAlgorithmOptimizer().optimize(request())
    pso_result = ga_result.model_copy(update={"algorithm": "pso"})
    with database.connect() as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_pso BEFORE INSERT ON optimizer_runs
            WHEN NEW.algorithm = 'pso' BEGIN SELECT RAISE(ABORT, 'test failure'); END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="test failure"):
        database.save_optimizer_results([ga_result, pso_result])

    assert database.list_optimizer_results() == []


def test_database_returns_typed_optimizer_run(tmp_path: Path) -> None:
    config_path = tmp_path / "parking.yaml"
    write_config(config_path)
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'parking.db'}",
        parking_config_path=config_path,
    )
    database = Database(settings.database_path)
    database.initialize(settings.parking.slots)
    database.save_optimizer_results([GeneticAlgorithmOptimizer().optimize(request())])

    saved = database.list_optimizer_results()

    assert len(saved) == 1
    assert isinstance(saved[0], PersistedOptimizerRun)
    assert saved[0].scenario_id == "same-scenario"


def test_optimizer_benchmark_api_persists_identical_scenario_results(tmp_path: Path) -> None:
    config_path = tmp_path / "parking.yaml"
    write_config(config_path)
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'parking.db'}",
        parking_config_path=config_path,
    )
    payload = {"algorithm": "all", "request": request().model_dump()}

    with TestClient(create_app(settings)) as client:
        run_response = client.post("/api/allocation/run", json=payload)
        list_response = client.get("/api/benchmarks/optimizers")

    assert run_response.status_code == 200
    results = run_response.json()["results"]
    assert {result["algorithm"] for result in results} == {"ga", "pso", "aco"}
    assert {result["scenario_id"] for result in results} == {"same-scenario"}
    assert {result["chosen_slot_id"] for result in results} <= {2, 3, 4, 5}
    assert list_response.status_code == 200
    assert len(list_response.json()["runs"]) == 3


def test_allocation_api_returns_structured_full_capacity_error(tmp_path: Path) -> None:
    config_path = tmp_path / "parking.yaml"
    write_config(config_path)
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'parking.db'}",
        parking_config_path=config_path,
    )
    payload = {
        "algorithm": "ga",
        "request": request(all_occupied=True).model_dump(),
    }

    with TestClient(create_app(settings)) as client:
        response = client.post("/api/allocation/run", json=payload)

    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "code": "no_available_slot",
            "message": "no parking slot is available",
        }
    }
