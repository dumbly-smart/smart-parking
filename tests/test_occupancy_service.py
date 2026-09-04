from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from pathlib import Path

import pytest

from backend.app.config import SlotConfig
from backend.app.db import Database
from backend.app.services.occupancy import OccupancyService
from vision.models import DetectorObservation


class FakeDetector:
    def __init__(self, frames: Sequence[tuple[DetectorObservation, ...]]) -> None:
        self._frames = iter(frames)

    def detect(self, image_bytes: bytes) -> tuple[DetectorObservation, ...]:
        return next(self._frames)


def observation(
    slot_id: int,
    occupied: bool,
    *,
    confidence: float = 1.0,
    score: float | None = None,
) -> DetectorObservation:
    return DetectorObservation(
        slot_id=slot_id,
        candidate_occupied=occupied,
        score=float(occupied) if score is None else score,
        confidence=confidence,
    )


def initialized_database(tmp_path: Path, slot_ids: tuple[int, ...] = (1,)) -> Database:
    database = Database(tmp_path / "parking.db")
    database.initialize(
        [
            SlotConfig(
                id=slot_id,
                name=f"S{slot_id}",
                walking_distance=0.5,
                zone="test",
            )
            for slot_id in slot_ids
        ]
    )
    return database


def service_for(
    database: Database,
    frames: Sequence[tuple[DetectorObservation, ...]],
) -> OccupancyService:
    return OccupancyService(
        database,
        FakeDetector(frames),
        minimum_confidence=0.7,
        required_consecutive_frames=3,
    )


def persisted_occupancy(database: Database) -> dict[int, int]:
    with sqlite3.connect(database.path) as connection:
        return dict(connection.execute("SELECT id, occupied FROM parking_slots ORDER BY id"))


def persisted_events(database: Database) -> list[tuple[int, int, float, str, str]]:
    with sqlite3.connect(database.path) as connection:
        return connection.execute(
            """
            SELECT slot_id, occupied, confidence, source, observed_at
            FROM occupancy_events ORDER BY id
            """
        ).fetchall()


def test_confident_change_is_pending_twice_then_persisted_once(tmp_path: Path) -> None:
    database = initialized_database(tmp_path)
    occupied = (observation(1, True, confidence=0.82, score=0.45),)
    service = service_for(database, [occupied, occupied, occupied, occupied])

    first = service.process(b"frame-1")
    second = service.process(b"frame-2")
    third = service.process(b"frame-3")
    fourth = service.process(b"frame-4")

    assert [first.slots[0].outcome, second.slots[0].outcome] == ["pending", "pending"]
    assert [first.slots[0].consecutive_frames, second.slots[0].consecutive_frames] == [1, 2]
    assert third.slots[0].outcome == "accepted"
    assert third.slots[0].accepted_occupied is True
    assert third.slots[0].consecutive_frames == 0
    assert fourth.slots[0].outcome == "unchanged"
    assert persisted_occupancy(database) == {1: 1}
    events = persisted_events(database)
    assert [(event[0], event[1], event[2], event[3]) for event in events] == [
        (1, 1, 0.82, "camera_heuristic")
    ]
    assert third.observed_at.endswith("Z")
    assert events[0][4] == third.observed_at


def test_slots_keep_independent_streaks(tmp_path: Path) -> None:
    database = initialized_database(tmp_path, (2, 9))
    service = service_for(
        database,
        [
            (observation(2, True), observation(9, False)),
            (observation(2, True), observation(9, True)),
            (observation(2, True), observation(9, True)),
            (observation(2, True), observation(9, True)),
        ],
    )

    first = service.process(b"frame-1")
    second = service.process(b"frame-2")
    third = service.process(b"frame-3")
    fourth = service.process(b"frame-4")

    assert [(slot.outcome, slot.consecutive_frames) for slot in first.slots] == [
        ("pending", 1),
        ("unchanged", 0),
    ]
    assert [(slot.outcome, slot.consecutive_frames) for slot in second.slots] == [
        ("pending", 2),
        ("pending", 1),
    ]
    assert [(slot.outcome, slot.consecutive_frames) for slot in third.slots] == [
        ("accepted", 0),
        ("pending", 2),
    ]
    assert [(slot.outcome, slot.consecutive_frames) for slot in fourth.slots] == [
        ("unchanged", 0),
        ("accepted", 0),
    ]
    assert persisted_occupancy(database) == {2: 1, 9: 1}


def test_uncertain_observation_resets_streak(tmp_path: Path) -> None:
    database = initialized_database(tmp_path)
    service = service_for(
        database,
        [
            (observation(1, True),),
            (observation(1, True, confidence=0.69),),
            (observation(1, True),),
        ],
    )

    results = [service.process(f"frame-{index}".encode()) for index in range(3)]

    outcomes = [
        (result.slots[0].outcome, result.slots[0].consecutive_frames)
        for result in results
    ]
    assert outcomes == [
        ("pending", 1),
        ("pending", 0),
        ("pending", 1),
    ]
    assert persisted_occupancy(database) == {1: 0}


def test_unchanged_observation_resets_streak(tmp_path: Path) -> None:
    database = initialized_database(tmp_path)
    service = service_for(
        database,
        [
            (observation(1, True),),
            (observation(1, False),),
            (observation(1, True),),
        ],
    )

    results = [service.process(f"frame-{index}".encode()) for index in range(3)]

    outcomes = [
        (result.slots[0].outcome, result.slots[0].consecutive_frames)
        for result in results
    ]
    assert outcomes == [
        ("pending", 1),
        ("unchanged", 0),
        ("pending", 1),
    ]


def test_new_service_starts_with_empty_streaks_and_durable_occupancy(tmp_path: Path) -> None:
    database = initialized_database(tmp_path)
    occupied = (observation(1, True),)
    first_service = service_for(database, [occupied, occupied])
    first_service.process(b"frame-1")
    before_restart = first_service.process(b"frame-2")

    after_restart = service_for(database, [occupied]).process(b"frame-3")

    assert before_restart.slots[0].consecutive_frames == 2
    assert after_restart.slots[0].consecutive_frames == 1
    assert after_restart.slots[0].accepted_occupied is False
    assert persisted_occupancy(database) == {1: 0}


def test_free_transition_is_blocked_by_active_session_and_clears_streak(
    tmp_path: Path,
) -> None:
    database = initialized_database(tmp_path)
    with database.connect() as connection:
        vehicle_id = connection.execute(
            "INSERT INTO vehicles (rfid_uid) VALUES ('CARD-1')"
        ).lastrowid
        connection.execute(
            """
            INSERT INTO parking_sessions (vehicle_id, slot_id, entry_idempotency_key)
            VALUES (?, 1, 'entry-1')
            """,
            (vehicle_id,),
        )
        connection.execute("UPDATE parking_slots SET occupied = 1 WHERE id = 1")
    free = (observation(1, False),)
    service = service_for(database, [free, free, free, free])

    first = service.process(b"frame-1")
    service.process(b"frame-2")
    blocked = service.process(b"frame-3")
    after_block = service.process(b"frame-4")

    assert first.slots[0].accepted_occupied is True
    assert blocked.slots[0].outcome == "blocked"
    assert blocked.slots[0].accepted_occupied is True
    assert blocked.slots[0].consecutive_frames == 0
    assert after_block.slots[0].outcome == "pending"
    assert after_block.slots[0].consecutive_frames == 1
    assert persisted_occupancy(database) == {1: 1}
    assert persisted_events(database) == []


def test_event_failure_rolls_back_complete_frame_and_does_not_advance_streaks(
    tmp_path: Path,
) -> None:
    database = initialized_database(tmp_path, (1, 2))
    occupied = (observation(1, True), observation(2, True))
    service = service_for(database, [occupied, occupied, occupied, occupied])
    service.process(b"frame-1")
    service.process(b"frame-2")
    with database.connect() as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_second_camera_event
            BEFORE INSERT ON occupancy_events
            WHEN NEW.slot_id = 2
            BEGIN
                SELECT RAISE(FAIL, 'injected event failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="injected event failure"):
        service.process(b"frame-3")

    assert persisted_occupancy(database) == {1: 0, 2: 0}
    assert persisted_events(database) == []
    with database.connect() as connection:
        connection.execute("DROP TRIGGER fail_second_camera_event")

    retried = service.process(b"frame-4")

    assert [(slot.outcome, slot.consecutive_frames) for slot in retried.slots] == [
        ("accepted", 0),
        ("accepted", 0),
    ]
    assert persisted_occupancy(database) == {1: 1, 2: 1}
    assert len(persisted_events(database)) == 2
