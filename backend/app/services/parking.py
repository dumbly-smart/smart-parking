from __future__ import annotations

from collections import Counter

from backend.app.config import ObjectiveWeights
from backend.app.db import Database
from backend.app.models.parking import (
    EntryResponse,
    ExitResponse,
    ParkingSlotRecord,
    VehicleOperationRequest,
)
from optimization.benchmark import OPTIMIZERS
from optimization.models import AllocationRequest, AllocationResult, SlotCandidate


class ParkingService:
    def __init__(
        self, database: Database, selected_optimizer: str, weights: ObjectiveWeights
    ) -> None:
        self.database = database
        self.optimizer = OPTIMIZERS[selected_optimizer]
        self.weights = weights

    def enter(self, request: VehicleOperationRequest) -> EntryResponse:
        def allocate(slots: tuple[ParkingSlotRecord, ...]) -> AllocationResult:
            zone_totals = Counter(slot.zone for slot in slots)
            zone_occupied = Counter(slot.zone for slot in slots if slot.occupied)
            candidates = tuple(
                SlotCandidate(
                    slot_id=slot.id,
                    occupied=slot.occupied,
                    distance=slot.walking_distance,
                    congestion=zone_occupied[slot.zone] / zone_totals[slot.zone],
                    waiting=0.0,
                    fairness=0.0,
                )
                for slot in slots
            )
            return self.optimizer.optimize(
                AllocationRequest(
                    scenario_id=f"entry:{request.idempotency_key}",
                    candidates=candidates,
                    weights=self.weights,
                    seed=42,
                    iterations=30,
                )
            )

        return self.database.enter_vehicle(
            request.rfid_uid, request.idempotency_key, allocate
        )

    def exit(self, request: VehicleOperationRequest) -> ExitResponse:
        return self.database.exit_vehicle(request.rfid_uid, request.idempotency_key)
