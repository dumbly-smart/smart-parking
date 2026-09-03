from __future__ import annotations

from collections.abc import Iterable

from backend.app.db import Database
from optimization.aco import AntColonyOptimizer
from optimization.ga import GeneticAlgorithmOptimizer
from optimization.models import AllocationRequest, AllocationResult, Optimizer
from optimization.pso import ParticleSwarmOptimizer

OPTIMIZERS: dict[str, Optimizer] = {
    "ga": GeneticAlgorithmOptimizer(),
    "pso": ParticleSwarmOptimizer(),
    "aco": AntColonyOptimizer(),
}


class BenchmarkRunner:
    def __init__(self, database: Database) -> None:
        self.database = database

    def run(
        self, request: AllocationRequest, algorithms: Iterable[str] = ("ga", "pso", "aco")
    ) -> list[AllocationResult]:
        results = [OPTIMIZERS[name].optimize(request) for name in algorithms]
        self.database.save_optimizer_results(results)
        return results
