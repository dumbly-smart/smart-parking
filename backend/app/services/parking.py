from __future__ import annotations

import hashlib
from collections import Counter

from backend.app.config import ObjectiveWeights
from backend.app.db import Database
from backend.app.models.parking import (
    EntryResponse,
    ExitResponse,
    ParkingSlotRecord,
    ParkingStatusResponse,
    VehicleOperationRequest,
)
from optimization.benchmark import OPTIMIZERS
from optimization.models import AllocationRequest, AllocationResult, Optimizer, SlotCandidate


class ParkingService:
    def __init__(
        self,
        database: Database,
        optimizer_name: str,
        weights: ObjectiveWeights,
    ) -> None:
        self.database = database
        self.optimizer: Optimizer = OPTIMIZERS[optimizer_name]
        self.weights = weights

    def enter(self, request: VehicleOperationRequest) -> EntryResponse:
        return self.database.enter_vehicle(
            request.rfid_uid,
            request.idempotency_key,
            lambda slots: self._allocate(request, slots),
        )

    def exit(self, request: VehicleOperationRequest) -> ExitResponse:
        return self.database.exit_vehicle(request.rfid_uid, request.idempotency_key)

    def status(self) -> ParkingStatusResponse:
        return self.database.parking_status()

    def _allocate(
        self,
        request: VehicleOperationRequest,
        slots: tuple[ParkingSlotRecord, ...],
    ) -> AllocationResult:
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
        identity = f"{request.rfid_uid}:{request.idempotency_key}".encode()
        seed = int.from_bytes(hashlib.sha256(identity).digest()[:8], "big", signed=True)
        return self.optimizer.optimize(
            AllocationRequest(
                scenario_id=f"entry:{request.idempotency_key}",
                candidates=candidates,
                weights=self.weights,
                seed=seed,
                iterations=30,
            )
        )
