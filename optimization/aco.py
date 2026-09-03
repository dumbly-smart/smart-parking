from __future__ import annotations

import random
from time import perf_counter

from optimization.common import available_candidates, best_candidate, result_for
from optimization.fitness import weighted_cost
from optimization.models import AllocationRequest, AllocationResult


class AntColonyOptimizer:
    name = "aco"

    def optimize(self, request: AllocationRequest) -> AllocationResult:
        started_at = perf_counter()
        available = available_candidates(request)
        rng = random.Random(request.seed)
        pheromones = [1.0 for _ in available]
        best = rng.choice(available)
        for _ in range(request.iterations):
            desirability = [
                pheromones[index] / (weighted_cost(candidate, request.weights)[0] + 1e-9)
                for index, candidate in enumerate(available)
            ]
            chosen = rng.choices(available, weights=desirability, k=2)
            candidate = best_candidate(chosen, request)
            best = best_candidate([best, candidate], request)
            pheromones = [value * 0.8 for value in pheromones]
            pheromones[available.index(best)] += 1.0 / (
                weighted_cost(best, request.weights)[0] + 1e-9
            )
        return result_for(self.name, request, best, started_at)
