from __future__ import annotations

import random
from time import perf_counter

from optimization.common import available_candidates, best_candidate, result_for
from optimization.models import AllocationRequest, AllocationResult


class ParticleSwarmOptimizer:
    name = "pso"

    def optimize(self, request: AllocationRequest) -> AllocationResult:
        started_at = perf_counter()
        available = available_candidates(request)
        rng = random.Random(request.seed)
        positions = [rng.uniform(0, len(available) - 1) for _ in range(2)]
        velocities = [rng.uniform(-0.5, 0.5) for _ in positions]
        visited = [available[round(position)] for position in positions]
        personal_best = list(visited)
        best = best_candidate(visited, request)
        for _ in range(request.iterations):
            visited = [available[round(position)] for position in positions]
            personal_best = [
                best_candidate([old, current], request)
                for old, current in zip(personal_best, visited, strict=True)
            ]
            best = best_candidate([best, *personal_best], request)
            best_index = available.index(best)
            for index in range(len(positions)):
                personal_index = available.index(personal_best[index])
                velocities[index] = (
                    0.5 * velocities[index]
                    + rng.random() * (personal_index - positions[index])
                    + rng.random() * (best_index - positions[index])
                )
                positions[index] = min(
                    max(positions[index] + velocities[index], 0), len(available) - 1
                )
        return result_for(self.name, request, best, started_at)
