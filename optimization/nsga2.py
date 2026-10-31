from __future__ import annotations

import random
from time import perf_counter
from typing import Sequence

import numpy as np

from optimization.common import available_candidates, result_for
from optimization.models import AllocationRequest, AllocationResult, SlotCandidate


def _objectives(candidate: SlotCandidate) -> tuple[float, float, float, float]:
    return candidate.distance, candidate.congestion, candidate.waiting, candidate.fairness


def _dominates(left: SlotCandidate, right: SlotCandidate) -> bool:
    a, b = _objectives(left), _objectives(right)
    return all(x <= y for x, y in zip(a, b, strict=True)) and any(
        x < y for x, y in zip(a, b, strict=True)
    )


def _fronts(population: Sequence[SlotCandidate]) -> list[list[SlotCandidate]]:
    # Duplicate chromosomes add no new point to the Pareto set and make the
    # classic pairwise sort needlessly expensive for this discrete bay problem.
    population = tuple({candidate.slot_id: candidate for candidate in population}.values())
    objective_values = np.asarray([_objectives(candidate) for candidate in population])
    dominance = np.all(objective_values[:, None, :] <= objective_values[None, :, :], axis=2)
    dominance &= np.any(objective_values[:, None, :] < objective_values[None, :, :], axis=2)
    dominated_by = dominance.sum(axis=0).astype(int).tolist()
    dominates = [np.flatnonzero(dominance[index]).tolist() for index in range(len(population))]
    fronts: list[list[int]] = [[]]
    for i, candidate in enumerate(population):
        for j, other in enumerate(population):
            if i == j:
                continue
            if _dominates(candidate, other):
                dominates[i].append(j)
            elif _dominates(other, candidate):
                dominated_by[i] += 1
        if dominated_by[i] == 0:
            fronts[0].append(i)
    rank = 0
    while rank < len(fronts) and fronts[rank]:
        next_front: list[int] = []
        for i in fronts[rank]:
            for j in dominates[i]:
                dominated_by[j] -= 1
                if dominated_by[j] == 0:
                    next_front.append(j)
        if next_front:
            fronts.append(next_front)
        rank += 1
    return [[population[i] for i in front] for front in fronts]


def _crowding(front: Sequence[SlotCandidate]) -> dict[int, float]:
    distances = {id(candidate): 0.0 for candidate in front}
    if len(front) <= 2:
        return {key: float("inf") for key in distances}
    for objective in range(4):
        ordered = sorted(front, key=lambda item: _objectives(item)[objective])
        distances[id(ordered[0])] = distances[id(ordered[-1])] = float("inf")
        low = _objectives(ordered[0])[objective]
        high = _objectives(ordered[-1])[objective]
        if high == low:
            continue
        for index in range(1, len(ordered) - 1):
            key = id(ordered[index])
            if distances[key] != float("inf"):
                distances[key] += (
                    _objectives(ordered[index + 1])[objective]
                    - _objectives(ordered[index - 1])[objective]
                ) / (high - low)
    return distances


class NSGA2Optimizer:
    """NSGA-II over available bays; returns the weighted compromise in its Pareto set."""

    name = "nsga2"

    def optimize(self, request: AllocationRequest) -> AllocationResult:
        started_at = perf_counter()
        available = available_candidates(request)
        rng = random.Random(request.seed)
        size = request.population_size
        population = [rng.choice(available) for _ in range(size)]
        ranks: dict[int, int] = {}
        crowding: dict[int, float] = {}

        def rank_and_crowd(items: Sequence[SlotCandidate]) -> None:
            ranks.clear()
            crowding.clear()
            for rank, front in enumerate(_fronts(items)):
                distances = _crowding(front)
                for candidate in front:
                    ranks[id(candidate)] = rank
                    crowding[id(candidate)] = distances[id(candidate)]

        def tournament() -> SlotCandidate:
            if len(population) == 1:
                return population[0]
            left, right = rng.sample(population, 2)
            left_key = (ranks[id(left)], -crowding[id(left)], left.slot_id)
            right_key = (ranks[id(right)], -crowding[id(right)], right.slot_id)
            return left if left_key <= right_key else right

        rank_and_crowd(population)
        for _ in range(request.generations):
            offspring: list[SlotCandidate] = []
            while len(offspring) < size:
                first, second = tournament(), tournament()
                child = first if rng.random() < request.crossover_probability else second
                if rng.random() < request.mutation_probability:
                    child = rng.choice(available)
                offspring.append(child)
            combined = population + offspring
            next_population: list[SlotCandidate] = []
            for front in _fronts(combined):
                remaining = size - len(next_population)
                if len(front) <= remaining:
                    next_population.extend(front)
                else:
                    distances = _crowding(front)
                    next_population.extend(
                        sorted(front, key=lambda item: (-distances[id(item)], item.slot_id))[:remaining]
                    )
                    break
            population = next_population
            rank_and_crowd(population)

        pareto_front = _fronts(population)[0]
        chosen = min(
            pareto_front,
            key=lambda candidate: (
                candidate.distance * request.weights.distance
                + candidate.congestion * request.weights.congestion
                + candidate.waiting * request.weights.waiting
                + candidate.fairness * request.weights.fairness,
                candidate.slot_id,
            ),
        )
        result = result_for(self.name, request, chosen, started_at)
        return result.model_copy(update={"iterations": request.generations})
