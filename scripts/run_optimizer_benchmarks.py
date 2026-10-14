"""Run controlled GA/PSO/ACO comparisons against baseline and exact search."""

from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
import time
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

from backend.app.config import ObjectiveWeights, Settings
from optimization.aco import AntColonyOptimizer
from optimization.fitness import weighted_cost
from optimization.ga import GeneticAlgorithmOptimizer
from optimization.models import AllocationRequest, NoAvailableSlotError, SlotCandidate
from optimization.pso import ParticleSwarmOptimizer

DEFAULT_OUTPUT = Path("review_outputs/2026-10-15/optimization_results")
ALGORITHMS = {
    "GA": GeneticAlgorithmOptimizer(),
    "PSO": ParticleSwarmOptimizer(),
    "ACO": AntColonyOptimizer(),
}
OCCUPANCY_LEVELS = ("empty", "light", "moderate", "heavy", "near_full", "full")


def _scenario(
    index: int,
    seed: int,
    weights: ObjectiveWeights,
    scenario_count: int = 120,
) -> AllocationRequest:
    rng = random.Random(seed)
    occupied_count = min((index * 6) // scenario_count, 5)
    slot_ids = list(range(1, 6))
    occupied = set(rng.sample(slot_ids, occupied_count))
    candidates = tuple(
        SlotCandidate(
            slot_id=slot_id,
            occupied=slot_id in occupied,
            distance=round(rng.random(), 6),
            congestion=round(rng.random(), 6),
            waiting=round(rng.random(), 6),
            fairness=round(rng.random(), 6),
        )
        for slot_id in slot_ids
    )
    return AllocationRequest(
        scenario_id=f"review-{index:03d}",
        candidates=candidates,
        weights=weights,
        seed=seed,
        iterations=30,
    )


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
) -> dict[str, object]:
    occupied_count = sum(candidate.occupied for candidate in request.candidates)
    row: dict[str, object] = {
        "scenario_id": request.scenario_id,
        "repeat_seed": request.seed,
        "occupancy_level": OCCUPANCY_LEVELS[occupied_count],
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
    output: Path, *, scenario_count: int = 120, repeats: int = 3
) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    settings = Settings()
    weights = settings.parking.allocation.weights
    rows: list[dict[str, object]] = []
    for scenario_index in range(scenario_count):
        for repetition in range(repeats):
            seed = 20261015 + scenario_index * 101 + repetition
            request = _scenario(scenario_index, seed, weights, scenario_count)
            available = tuple(
                candidate for candidate in request.candidates if not candidate.occupied
            )
            if available:
                exact = _exact_candidate(request)
                exact_cost = weighted_cost(exact, weights)[0]
                baseline = available[0]
                rows.append(
                    _measure("first_available", request, lambda _, baseline=baseline: baseline)
                )
                rows[-1]["exact_cost"] = exact_cost
                rows[-1]["optimality_gap"] = rows[-1]["objective_cost"] - exact_cost
                rows.append(_measure("exhaustive_optimum", request, _exact_candidate))
                rows[-1]["exact_cost"] = exact_cost
                rows[-1]["optimality_gap"] = 0.0
            else:
                exact_cost = None
                for label in ("first_available", "exhaustive_optimum"):
                    rows.append(
                        _measure(
                            label, request, lambda _: (_ for _ in ()).throw(NoAvailableSlotError())
                        )
                    )
            for name, optimizer in ALGORITHMS.items():
                row = _measure(name, request, optimizer.optimize)
                row["exact_cost"] = exact_cost if exact_cost is not None else ""
                if row["status"] == "success" and exact_cost is not None:
                    row["optimality_gap"] = max(0.0, float(row["objective_cost"]) - exact_cost)
                rows.append(row)

    fields = tuple(rows[0])
    runs_path = output / "benchmark_runs.csv"
    with runs_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
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
                "success_rate": len(group) / (scenario_count * repeats),
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
        writer = csv.DictWriter(stream, fieldnames=summary_fields)
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
    summary: dict[str, object] = {
        "scenario_count": scenario_count,
        "repeated_seeds_per_scenario": repeats,
        "successful_scenario_repetitions": scenario_count * repeats
        - sum(1 for index in range(scenario_count) if min((index * 6) // scenario_count, 5) == 5)
        * repeats,
        "full_capacity_rejections": len(full_rows),
        "weights": weights.model_dump(),
        "iterations": 30,
        "random_seed_formula": "20261015 + scenario_index * 101 + repetition",
        "occupancy_levels": {
            level: sum(
                min((index * 6) // scenario_count, 5) == occupied for index in range(scenario_count)
            )
            for occupied, level in enumerate(OCCUPANCY_LEVELS)
        },
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
        "interpretation": "Simulation-based single-slot objective and software runtime; not physical throughput or measured waiting time.",  # noqa: E501
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
    display_algorithms = ("GA", "PSO", "ACO", "first_available", "exhaustive_optimum")
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
    axis.boxplot(gap_values, tick_labels=labels, showfliers=True)
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
    parser.add_argument("--scenarios", type=int, default=120)
    parser.add_argument("--repeats", type=int, default=3)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.scenarios < 100 or args.repeats < 2:
        raise SystemExit("use at least 100 distinct scenarios and two repeats")
    summary = run_experiments(args.output_dir, scenario_count=args.scenarios, repeats=args.repeats)
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
