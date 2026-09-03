from __future__ import annotations

import random
from time import perf_counter

from optimization.common import available_candidates, best_candidate, result_for
from optimization.fitness import weighted_cost
from optimization.models import AllocationRequest, AllocationResult


class GeneticAlgorithmOptimizer:
    name = "ga"

    def optimize(self, request: AllocationRequest) -> AllocationResult:
        started_at = perf_counter()
        available = available_candidates(request)
        rng = random.Random(request.seed)
        population = [rng.choice(available) for _ in range(2)]
        best = population[0]
        for _ in range(request.iterations):
            candidate = best_candidate(population, request)
            best = best_candidate([best, candidate], request)
            parent = min(
                population,
                key=lambda item: (weighted_cost(item, request.weights)[0], item.slot_id),
            )
            population = [parent, rng.choice(available)]
        return result_for(self.name, request, best, started_at)
