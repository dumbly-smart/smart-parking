"""Run controlled GA/PSO/ACO/NSGA-II comparisons against baseline and exact search."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import socket
import statistics
import subprocess
import tempfile
import time
import uuid
from collections import defaultdict
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from optimization.aco import AntColonyOptimizer
from optimization.fitness import weighted_cost
from optimization.ga import GeneticAlgorithmOptimizer
from optimization.models import AllocationRequest, NoAvailableSlotError, SlotCandidate
from optimization.nsga2 import NSGA2Optimizer
from optimization.pso import ParticleSwarmOptimizer

DEFAULT_OUTPUT = Path("review_outputs/2026-10-15/optimization_results")
DEFAULT_SUMO_SEED = 20261031
ALGORITHMS = {
    "GA": GeneticAlgorithmOptimizer(),
    "PSO": ParticleSwarmOptimizer(),
    "ACO": AntColonyOptimizer(),
    "NSGA-II": NSGA2Optimizer(),
}
OCCUPANCY_LEVELS = ("empty", "light", "moderate", "heavy", "near_full", "full")
SLOT_COUNT = 2_376


@dataclass(frozen=True)
class ObservedScenario:
    request: AllocationRequest
    simulation_time: float
    traffic_vehicle_count: int
    parked_vehicle_count: int


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_sumo_scenarios(
    scenario_limit: int, *, sumo_seed: int
) -> tuple[list[ObservedScenario], dict[str, object]]:
    """Observe real TraCI parking admissions using the application's live allocator."""
    if scenario_limit < 1:
        raise ValueError("scenario_limit must be positive")

    from fastapi.testclient import TestClient

    from backend.app.main import create_app

    previous_environment = {
        name: os.environ.get(name)
        for name in ("SMART_PARKING_DATABASE_URL", "SMART_PARKING_SELECTED_OPTIMIZER")
    }
    observations: list[ObservedScenario] = []
    metadata: dict[str, object] = {}
    with tempfile.TemporaryDirectory(prefix="smart-parking-sumo-benchmark-") as temp_dir:
        database_path = Path(temp_dir) / "benchmark.sqlite3"
        os.environ["SMART_PARKING_DATABASE_URL"] = f"sqlite:///{database_path}"
        os.environ["SMART_PARKING_SELECTED_OPTIMIZER"] = "nsga2"
        try:
            app = create_app()
            with TestClient(app):
                settings = app.state.settings
                sumo_service = app.state.sumo_service
                if not sumo_service.status()["available"]:
                    raise RuntimeError(sumo_service.status()["error"] or "SUMO is unavailable")
                binary = sumo_service._binary_path()
                traci = sumo_service._load_traci()
                optimizer = app.state.parking_service.optimizer
                original_optimize = optimizer.optimize
                capture_context = {
                    "simulation_time": 0.0,
                    "traffic_vehicle_count": 0,
                    "parked_vehicle_count": 0,
                }

                def capture_request(request: AllocationRequest):
                    if len(observations) < scenario_limit:
                        observations.append(
                            ObservedScenario(
                                request=request,
                                simulation_time=float(capture_context["simulation_time"]),
                                traffic_vehicle_count=int(capture_context["traffic_vehicle_count"]),
                                parked_vehicle_count=int(capture_context["parked_vehicle_count"]),
                            )
                        )
                    return original_optimize(request)

                optimizer.optimize = capture_request
                process = None
                connection = None
                log_stream = None
                try:
                    with socket.socket() as probe:
                        probe.bind(("127.0.0.1", 0))
                        port = probe.getsockname()[1]
                    log_path = Path(temp_dir) / "sumo.log"
                    log_stream = log_path.open("w", encoding="utf-8")
                    process = subprocess.Popen(
                        [
                            binary,
                            "-c",
                            str(settings.sumo_config_path),
                            "--step-length",
                            str(settings.sumo_step_length),
                            "--seed",
                            str(sumo_seed),
                            "--remote-port",
                            str(port),
                            "--no-step-log",
                            "true",
                        ],
                        stdin=subprocess.DEVNULL,
                        stdout=log_stream,
                        stderr=subprocess.STDOUT,
                    )
                    connection = traci.connect(
                        port=port,
                        host="127.0.0.1",
                        proc=process,
                        numRetries=60,
                        waitBetweenRetries=0.1,
                        label=f"optimizer-benchmark-{uuid.uuid4().hex}",
                    )
                    parking_traffic = sumo_service.parking_traffic
                    max_steps = int(3600 / settings.sumo_step_length) + 1
                    for _ in range(max_steps):
                        if len(observations) >= scenario_limit:
                            break
                        connection.simulationStep()
                        vehicle_ids = connection.vehicle.getIDList()
                        vehicles = []
                        for vehicle_id in vehicle_ids[:1200]:
                            x, y, elevation = connection.vehicle.getPosition3D(vehicle_id)
                            road_id = connection.vehicle.getRoadID(vehicle_id)
                            vehicles.append(
                                {
                                    "id": vehicle_id,
                                    "x": float(x),
                                    "y": float(y),
                                    "elevation": float(elevation),
                                    "floor": max(
                                        1,
                                        min(
                                            6,
                                            round(elevation / sumo_service.floor_height)
                                            + sumo_service.ground_floor,
                                        ),
                                    ),
                                    "road_id": road_id,
                                    "in_city": road_id.startswith(("city_", ":C")),
                                    "on_ramp": road_id.startswith(("up_", "down_"))
                                    or abs(
                                        elevation / sumo_service.floor_height
                                        - round(elevation / sumo_service.floor_height)
                                    )
                                    > 0.02,
                                    "speed_mps": float(connection.vehicle.getSpeed(vehicle_id)),
                                    "angle": float(connection.vehicle.getAngle(vehicle_id)),
                                }
                            )
                        simulation_time = float(connection.simulation.getTime())
                        capture_context.update(
                            simulation_time=simulation_time,
                            traffic_vehicle_count=len(vehicle_ids),
                            parked_vehicle_count=len(parking_traffic.active),
                        )
                        parking_traffic.step(connection, vehicles, simulation_time)
                        with sumo_service._lock:
                            sumo_service._snapshot = {
                                **sumo_service._empty_snapshot(),
                                "simulation_time": simulation_time,
                                "vehicle_count": len(vehicle_ids),
                                "vehicles": vehicles,
                            }
                    if len(observations) < scenario_limit:
                        raise RuntimeError(
                            f"SUMO produced {len(observations)} parking arrivals; "
                            f"{scenario_limit} were requested"
                        )
                    if len(observations) != scenario_limit:
                        raise RuntimeError("SUMO benchmark captured an unexpected arrival count")
                    if any(len(item.request.candidates) != SLOT_COUNT for item in observations):
                        raise RuntimeError(
                            "SUMO observation did not include the full garage capacity"
                        )
                    with app.state.database.connect() as database_connection:
                        actual_sessions = int(
                            database_connection.execute(
                                "SELECT COUNT(*) FROM parking_sessions"
                            ).fetchone()[0]
                        )
                    if actual_sessions < scenario_limit:
                        raise RuntimeError(
                            "captured allocations do not match persisted parking sessions"
                        )
                    route_path = settings.sumo_config_path.parent / "garage.rou.xml"
                    network_path = settings.sumo_config_path.parent / "garage.net.xml"
                    version_output = subprocess.run(
                        [binary, "--version"], check=True, capture_output=True, text=True
                    ).stdout.splitlines()[0]
                    metadata = {
                        "source": "executed_sumo_parking_allocations",
                        "sumo_seed": sumo_seed,
                        "sumo_version": version_output,
                        "sumo_config_sha256": _sha256(settings.sumo_config_path),
                        "sumo_routes_sha256": _sha256(route_path),
                        "sumo_network_sha256": _sha256(network_path),
                        "sumo_step_length_seconds": settings.sumo_step_length,
                        "actual_persisted_parking_sessions": actual_sessions,
                        "observed_simulation_start": observations[0].simulation_time,
                        "observed_simulation_end": observations[-1].simulation_time,
                    }
                finally:
                    if connection is not None:
                        with suppress(Exception):
                            connection.close(wait=False)
                    if process is not None and process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
                    if log_stream is not None:
                        log_stream.close()
                    optimizer.optimize = original_optimize
        finally:
            for name, value in previous_environment.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
    return observations, metadata


def _exact_candidate(request: AllocationRequest) -> SlotCandidate:
    available = tuple(candidate for candidate in request.candidates if not candidate.occupied)
    if not available:
        raise NoAvailableSlotError("no parking slot is available")
    return min(
        available,
        key=lambda item: (weighted_cost(item, request.weights)[0], item.slot_id),
    )


def _measure(
    name: str,
    request: AllocationRequest,
    function: object,
    observed: ObservedScenario,
    repeat_seed: int,
) -> dict[str, object]:
    occupied_count = sum(candidate.occupied for candidate in request.candidates)
    occupancy_ratio = occupied_count / len(request.candidates)
    occupancy_level = (
        "empty" if occupancy_ratio == 0 else
        "full" if occupancy_ratio == 1 else
        "light" if occupancy_ratio < 0.2 else
        "moderate" if occupancy_ratio < 0.5 else
        "heavy" if occupancy_ratio < 0.8 else "near_full"
    )
    row: dict[str, object] = {
        "scenario_id": request.scenario_id,
        "source": "SUMO-observed",
        "observed_simulation_time": observed.simulation_time,
        "traffic_vehicle_count": observed.traffic_vehicle_count,
        "parked_vehicle_count": observed.parked_vehicle_count,
        "repeat_seed": repeat_seed,
        "occupancy_level": occupancy_level,
        "occupied_slots": occupied_count,
        "capacity": len(request.candidates),
        "algorithm": name,
        "status": "full_capacity" if occupied_count == len(request.candidates) else "success",
        "chosen_slot_id": "",
        "objective_cost": "",
        "exact_cost": "",
        "optimality_gap": "",
        "runtime_ms": 0.0,
        "invalid_assignment": False,
        "distance": "",
        "congestion": "",
        "waiting": "",
        "fairness": "",
    }
    start = time.perf_counter_ns()
    try:
        result = function(request)  # type: ignore[operator]
    except NoAvailableSlotError:
        row["runtime_ms"] = (time.perf_counter_ns() - start) / 1_000_000
        return row
    row["runtime_ms"] = (time.perf_counter_ns() - start) / 1_000_000
    chosen_slot_id = result.slot_id if isinstance(result, SlotCandidate) else result.chosen_slot_id
    breakdown = result if isinstance(result, SlotCandidate) else result.objective_breakdown
    objective_cost = weighted_cost(breakdown, request.weights)[0]
    selected = next(
        (candidate for candidate in request.candidates if candidate.slot_id == chosen_slot_id),
        None,
    )
    invalid = selected is None or selected.occupied
    row.update(
        status="invalid" if invalid else "success",
        chosen_slot_id=chosen_slot_id,
        objective_cost=objective_cost,
        invalid_assignment=invalid,
        distance=breakdown.distance,
        congestion=breakdown.congestion,
        waiting=breakdown.waiting,
        fairness=breakdown.fairness,
    )
    return row


def run_experiments(
    output: Path,
    observed_scenarios: Sequence[ObservedScenario],
    *,
    repeats: int = 3,
    sumo_metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    if not observed_scenarios:
        raise ValueError("at least one observed SUMO allocation is required")
    if repeats < 1:
        raise ValueError("repeats must be positive")
    capacities = {len(item.request.candidates) for item in observed_scenarios}
    if len(capacities) != 1:
        raise ValueError("observed SUMO scenarios must share one garage capacity")
    candidate_capacity = capacities.pop()
    output.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for observed in observed_scenarios:
        base_request = observed.request
        for repetition in range(repeats):
            seed = base_request.seed + repetition
            request = base_request.model_copy(update={"seed": seed})
            available = tuple(
                candidate for candidate in request.candidates if not candidate.occupied
            )
            if available:
                exact = _exact_candidate(request)
                exact_cost = weighted_cost(exact, request.weights)[0]
                baseline = available[0]
                rows.append(
                    _measure(
                        "first_available", request, lambda _, baseline=baseline: baseline,
                        observed, seed,
                    )
                )
                rows[-1]["exact_cost"] = exact_cost
                rows[-1]["optimality_gap"] = rows[-1]["objective_cost"] - exact_cost
                rows.append(
                    _measure("exhaustive_optimum", request, _exact_candidate, observed, seed)
                )
                rows[-1]["exact_cost"] = exact_cost
                rows[-1]["optimality_gap"] = 0.0
            else:
                exact_cost = None
                for label in ("first_available", "exhaustive_optimum"):
                    rows.append(
                        _measure(
                            label,
                            request,
                            lambda _: (_ for _ in ()).throw(NoAvailableSlotError()),
                            observed,
                            seed,
                        )
                    )
            for name, optimizer in ALGORITHMS.items():
                row = _measure(name, request, optimizer.optimize, observed, seed)
                row["exact_cost"] = exact_cost if exact_cost is not None else ""
                if row["status"] == "success" and exact_cost is not None:
                    row["optimality_gap"] = max(0.0, float(row["objective_cost"]) - exact_cost)
                rows.append(row)

    fields = tuple(rows[0])
    runs_path = output / "benchmark_runs.csv"
    with runs_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    successful = [row for row in rows if row["status"] == "success"]
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    occupancy_groups: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in successful:
        groups[str(row["algorithm"])].append(row)
        occupancy_groups[(str(row["algorithm"]), str(row["occupancy_level"]))].append(row)
    summary_rows = []
    for algorithm, group in groups.items():
        costs = [float(row["objective_cost"]) for row in group]
        runtimes = [float(row["runtime_ms"]) for row in group]
        gaps = [float(row["optimality_gap"]) for row in group if row["optimality_gap"] != ""]
        summary_rows.append(
            {
                "algorithm": algorithm,
                "successful_runs": len(group),
                "success_rate": len(group) / (len(observed_scenarios) * repeats),
                "invalid_assignments": sum(bool(row["invalid_assignment"]) for row in group),
                "mean_cost": statistics.mean(costs),
                "median_cost": statistics.median(costs),
                "std_cost": statistics.pstdev(costs),
                "mean_runtime_ms": statistics.mean(runtimes),
                "median_runtime_ms": statistics.median(runtimes),
                "std_runtime_ms": statistics.pstdev(runtimes),
                "p95_runtime_ms": sorted(runtimes)[int(0.95 * (len(runtimes) - 1))],
                "mean_optimality_gap": statistics.mean(gaps),
                "median_optimality_gap": statistics.median(gaps),
                "p95_optimality_gap": sorted(gaps)[int(0.95 * (len(gaps) - 1))],
                "mean_distance": statistics.mean(float(row["distance"]) for row in group),
                "mean_congestion": statistics.mean(float(row["congestion"]) for row in group),
                "mean_waiting": statistics.mean(float(row["waiting"]) for row in group),
                "mean_fairness": statistics.mean(float(row["fairness"]) for row in group),
            }
        )
    summary_fields = tuple(summary_rows[0])
    with (output / "optimizer_comparison.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=summary_fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(summary_rows)
    by_occupancy = {
        f"{algorithm}:{occupancy}": {
            "runs": len(group),
            "mean_cost": statistics.mean(float(row["objective_cost"]) for row in group),
            "mean_runtime_ms": statistics.mean(float(row["runtime_ms"]) for row in group),
        }
        for (algorithm, occupancy), group in occupancy_groups.items()
    }
    full_rows = [row for row in rows if row["status"] == "full_capacity"]
    scenario_levels = defaultdict(int)
    successful_repetitions = 0
    for observed in observed_scenarios:
        occupied = sum(candidate.occupied for candidate in observed.request.candidates)
        ratio = occupied / len(observed.request.candidates)
        level = (
            "empty" if ratio == 0 else
            "full" if ratio == 1 else
            "light" if ratio < 0.2 else
            "moderate" if ratio < 0.5 else
            "heavy" if ratio < 0.8 else "near_full"
        )
        scenario_levels[level] += 1
        if occupied < len(observed.request.candidates):
            successful_repetitions += repeats
    metadata = sumo_metadata or {}
    scenario_evidence_path = output / "sumo_observed_scenarios.jsonl"
    with scenario_evidence_path.open("w", encoding="utf-8") as stream:
        for observed in observed_scenarios:
            request = observed.request
            stream.write(
                json.dumps(
                    {
                        "scenario_id": request.scenario_id,
                        "simulation_time": observed.simulation_time,
                        "traffic_vehicle_count": observed.traffic_vehicle_count,
                        "parked_vehicle_count": observed.parked_vehicle_count,
                        "weights": request.weights.model_dump(),
                        "seed": request.seed,
                        "candidates": [item.model_dump() for item in request.candidates],
                    },
                    sort_keys=True,
                )
                + "\n"
            )
    summary: dict[str, object] = {
        **metadata,
        "source": "executed_sumo_parking_allocations",
        "scenario_count": len(observed_scenarios),
        "repeated_seeds_per_scenario": repeats,
        "candidate_capacity": candidate_capacity,
        "successful_scenario_repetitions": successful_repetitions,
        "full_capacity_rejections": len(full_rows),
        "weights": observed_scenarios[0].request.weights.model_dump(),
        "iterations": 30,
        "nsga2_parameters": {
            "population_size": 48,
            "generations": 60,
            "crossover_probability": 0.9,
            "mutation_probability": 0.12,
        },
        "optimizer_seed_strategy": "observed_allocation_seed + repeat_index",
        "occupancy_levels": dict(scenario_levels),
        "by_occupancy": by_occupancy,
        "success_failure_counts": {
            algorithm: {
                "success": sum(
                    row["status"] == "success" for row in rows if row["algorithm"] == algorithm
                ),
                "full_capacity": sum(
                    row["status"] == "full_capacity"
                    for row in rows
                    if row["algorithm"] == algorithm
                ),
                "invalid": sum(
                    row["status"] == "invalid" for row in rows if row["algorithm"] == algorithm
                ),
            }
            for algorithm in (*ALGORITHMS, "first_available", "exhaustive_optimum")
        },
        "scenario_evidence_file": scenario_evidence_path.name,
        "interpretation": "Measured optimizer outcomes on parking allocation states observed during an executed SUMO/TraCI run. This is simulation evidence, not a physical facility trial; waiting is zero because live allocation does not measure queue delay.",  # noqa: E501
    }
    (output / "optimizer_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _create_figures(output, rows, summary_rows)
    return summary


def _create_figures(
    output: Path,
    rows: list[dict[str, object]],
    summaries: list[dict[str, object]],
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures = output / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    successful = [row for row in rows if row["status"] == "success"]
    display_algorithms = ("GA", "PSO", "ACO", "NSGA-II", "first_available", "exhaustive_optimum")
    summary_map = {str(row["algorithm"]): row for row in summaries}

    for metric, title, ylabel, filename in (
        (
            "mean_cost",
            "Mean allocation objective cost",
            "Weighted objective cost (lower is better)",
            "average_allocation_cost.png",
        ),
        (
            "mean_runtime_ms",
            "Median software execution time",
            "Runtime (ms per allocation)",
            "execution_time.png",
        ),
    ):
        figure, axis = plt.subplots(figsize=(9, 5), dpi=180)
        field = "median_runtime_ms" if metric == "mean_runtime_ms" else metric
        labels = [name for name in display_algorithms if name in summary_map]
        axis.bar(labels, [summary_map[name][field] for name in labels])
        axis.set(title=title, ylabel=ylabel)
        axis.tick_params(axis="x", rotation=18)
        axis.grid(axis="y", alpha=0.25)
        figure.tight_layout()
        figure.savefig(figures / filename)
        plt.close(figure)

    figure, axis = plt.subplots(figsize=(10, 6), dpi=180)
    for algorithm in ALGORITHMS:
        means = []
        for level in OCCUPANCY_LEVELS[:-1]:
            values = [
                float(row["objective_cost"])
                for row in successful
                if row["algorithm"] == algorithm and row["occupancy_level"] == level
            ]
            means.append(statistics.mean(values) if values else float("nan"))
        axis.plot(OCCUPANCY_LEVELS[:-1], means, marker="o", label=algorithm)
    axis.set(
        title="Allocation objective cost by occupancy level",
        xlabel="Occupied slots",
        ylabel="Weighted objective cost",
    )
    axis.set_ylim(bottom=0)
    axis.legend()
    axis.grid(alpha=0.25)
    figure.tight_layout()
    figure.savefig(figures / "cost_by_occupancy.png")
    plt.close(figure)

    figure, axis = plt.subplots(figsize=(9, 5), dpi=180)
    labels = [name for name in display_algorithms if name in summary_map]
    gap_values = [
        [
            float(row["optimality_gap"])
            for row in successful
            if row["algorithm"] == name and row["optimality_gap"] != ""
        ]
        for name in labels
    ]
    gap_plot = axis.boxplot(
        gap_values,
        tick_labels=labels,
        showfliers=True,
        patch_artist=True,
    )
    palette = ("#2563EB", "#0F766E", "#F59E0B", "#7C3AED", "#DB2777", "#64748B")
    for index, box in enumerate(gap_plot["boxes"]):
        color = palette[index % len(palette)]
        box.set_facecolor(color)
        box.set_edgecolor(color)
        box.set_alpha(0.28)
    for index, median in enumerate(gap_plot["medians"]):
        median.set_color(palette[index % len(palette)])
        median.set_linewidth(1.6)
    for index, item in enumerate(gap_plot["whiskers"] + gap_plot["caps"]):
        item.set_color(palette[(index // 2) % len(palette)])
    axis.set(
        title="Optimality gap relative to exhaustive search",
        ylabel="Objective cost gap (lower is better)",
    )
    axis.set_ylim(bottom=0)
    axis.tick_params(axis="x", rotation=18)
    axis.grid(axis="y", alpha=0.25)
    figure.tight_layout()
    figure.savefig(figures / "optimality_gap_distribution.png")
    plt.close(figure)

    figure, axis = plt.subplots(figsize=(10, 6), dpi=180)
    component_names = ("distance", "congestion", "waiting", "fairness")
    x = list(range(len(component_names)))
    width = 0.8 / len(display_algorithms)
    for index, algorithm in enumerate(display_algorithms):
        group = [row for row in successful if row["algorithm"] == algorithm]
        if group:
            means = [statistics.mean(float(row[name]) for row in group) for name in component_names]
            axis.bar([value + index * width for value in x], means, width=width, label=algorithm)
    axis.set(
        title="Mean selected-slot objective components",
        ylabel="Normalized component value",
        xticks=[value + width * 2 for value in x],
        xticklabels=component_names,
    )
    axis.legend(ncol=2)
    axis.grid(axis="y", alpha=0.25)
    figure.tight_layout()
    figure.savefig(figures / "objective_components.png")
    plt.close(figure)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--scenarios",
        type=int,
        default=120,
        help="number of parking admissions to observe in SUMO",
    )
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--sumo-seed", type=int, default=DEFAULT_SUMO_SEED)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.scenarios < 1 or args.repeats < 2:
        raise SystemExit("request at least one observed SUMO arrival and two optimizer repeats")
    observations, metadata = collect_sumo_scenarios(
        args.scenarios,
        sumo_seed=args.sumo_seed,
    )
    summary = run_experiments(
        args.output_dir,
        observations,
        repeats=args.repeats,
        sumo_metadata=metadata,
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
