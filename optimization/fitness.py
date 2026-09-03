from __future__ import annotations

from backend.app.config import ObjectiveWeights
from optimization.models import ObjectiveBreakdown, SlotCandidate


def weighted_cost(
    candidate: SlotCandidate, weights: ObjectiveWeights
) -> tuple[float, ObjectiveBreakdown]:
    breakdown = ObjectiveBreakdown.model_validate(candidate.model_dump())
    cost = (
        weights.distance * candidate.distance
        + weights.congestion * candidate.congestion
        + weights.waiting * candidate.waiting
        + weights.fairness * candidate.fairness
    )
    return cost, breakdown
