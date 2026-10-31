from __future__ import annotations

from backend.app.services.parking_traffic import (
    _sumo_operation_key,
    _sumo_vehicle_uid,
)


def test_sumo_identity_is_stable_across_simulation_runs() -> None:
    first_run_uid = _sumo_vehicle_uid("veh-018")
    restarted_run_uid = _sumo_vehicle_uid("veh-018")

    assert first_run_uid == restarted_run_uid
    assert first_run_uid.startswith("SUMO:")
    assert len(first_run_uid) <= 128
    assert first_run_uid != _sumo_vehicle_uid("veh-019")


def test_sumo_operation_keys_are_unique_per_run_and_operation() -> None:
    entry_key = _sumo_operation_key("run-1", "veh-018", "entry")

    assert len(entry_key) <= 128
    assert entry_key != _sumo_operation_key("run-2", "veh-018", "entry")
    assert entry_key != _sumo_operation_key("run-1", "veh-018", "exit")
