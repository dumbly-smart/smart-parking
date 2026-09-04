from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Protocol

from backend.app.db import Database
from backend.app.models.occupancy import (
    OccupancyTransition,
    OccupancyUpdateResponse,
    SlotOccupancyResult,
)
from vision.models import DetectorObservation


class OccupancyDetector(Protocol):
    def detect(self, image_bytes: bytes) -> tuple[DetectorObservation, ...]: ...


@dataclass(frozen=True)
class PendingState:
    candidate_occupied: bool
    consecutive_frames: int


class OccupancyService:
    def __init__(
        self,
        database: Database,
        detector: OccupancyDetector,
        *,
        minimum_confidence: float,
        required_consecutive_frames: int,
    ) -> None:
        if not 0 <= minimum_confidence <= 1:
            raise ValueError("minimum_confidence must be between zero and one")
        if required_consecutive_frames < 1:
            raise ValueError("required_consecutive_frames must be positive")
        self.database = database
        self.detector = detector
        self.minimum_confidence = minimum_confidence
        self.required_consecutive_frames = required_consecutive_frames
        self._pending: dict[int, PendingState] = {}
        self._lock = Lock()

    def process(self, image_bytes: bytes) -> OccupancyUpdateResponse:
        with self._lock:
            observations = self.detector.detect(image_bytes)
            observed_at = datetime.now(UTC).isoformat(timespec="milliseconds").replace(
                "+00:00", "Z"
            )
            accepted = {
                slot.id: slot.occupied for slot in self.database.parking_status().slots
            }
            proposed_pending = dict(self._pending)
            transitions: list[OccupancyTransition] = []
            proposed_results: list[SlotOccupancyResult] = []

            seen_slot_ids: set[int] = set()
            for item in observations:
                if item.slot_id in seen_slot_ids:
                    raise ValueError(f"detector returned duplicate slot ID {item.slot_id}")
                seen_slot_ids.add(item.slot_id)
                if item.slot_id not in accepted:
                    raise ValueError(f"detector returned unknown slot ID {item.slot_id}")

                accepted_occupied = accepted[item.slot_id]
                outcome = "pending"
                consecutive_frames = 0
                if item.candidate_occupied == accepted_occupied:
                    proposed_pending.pop(item.slot_id, None)
                    outcome = "unchanged"
                elif item.confidence < self.minimum_confidence:
                    proposed_pending.pop(item.slot_id, None)
                else:
                    previous = proposed_pending.get(item.slot_id)
                    consecutive_frames = (
                        previous.consecutive_frames + 1
                        if previous is not None
                        and previous.candidate_occupied == item.candidate_occupied
                        else 1
                    )
                    if consecutive_frames >= self.required_consecutive_frames:
                        transitions.append(
                            OccupancyTransition(
                                slot_id=item.slot_id,
                                occupied=item.candidate_occupied,
                                confidence=item.confidence,
                            )
                        )
                        proposed_pending.pop(item.slot_id, None)
                        consecutive_frames = 0
                        outcome = "accepted"
                    else:
                        proposed_pending[item.slot_id] = PendingState(
                            candidate_occupied=item.candidate_occupied,
                            consecutive_frames=consecutive_frames,
                        )

                proposed_results.append(
                    SlotOccupancyResult(
                        slot_id=item.slot_id,
                        candidate_occupied=item.candidate_occupied,
                        accepted_occupied=(
                            item.candidate_occupied if outcome == "accepted" else accepted_occupied
                        ),
                        score=item.score,
                        confidence=item.confidence,
                        outcome=outcome,
                        consecutive_frames=consecutive_frames,
                    )
                )

            blocked = self.database.apply_occupancy_transitions(transitions, observed_at)
            results = tuple(
                result.model_copy(
                    update={
                        "accepted_occupied": accepted[result.slot_id],
                        "outcome": "blocked",
                    }
                )
                if result.slot_id in blocked
                else result
                for result in proposed_results
            )
            self._pending = proposed_pending
            return OccupancyUpdateResponse(observed_at=observed_at, slots=results)
