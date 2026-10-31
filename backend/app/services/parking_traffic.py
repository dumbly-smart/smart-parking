"""SUMO-to-garage handoff, with durable parking sessions and timed departures."""
from __future__ import annotations

import hashlib
import logging
import uuid

from backend.app.models.parking import VehicleOperationRequest

log = logging.getLogger(__name__)


def _sumo_vehicle_uid(vehicle_id):
    """Keep a deterministic parking identity for the same SUMO vehicle."""
    identity = hashlib.sha256(str(vehicle_id).encode()).hexdigest()
    return f"SUMO:{identity}"


def _sumo_operation_key(run_id, vehicle_id, operation):
    """Give each run and operation its own bounded idempotency key."""
    value = f"{run_id}:{vehicle_id}:{operation}".encode()
    return f"sumo:{hashlib.sha256(value).hexdigest()}"

class ParkingTraffic:
    def __init__(self, parking):
        self.parking = parking
        self.run_id = uuid.uuid4().hex
        self.active = {}
        self.completed = set()
        self.close()

    def step(self, connection, vehicles, now):
        for vehicle_id, state in list(self.active.items()):
            if now < state['due']:
                continue
            if state['phase'] == 'parked':
                self.parking.exit(
                    VehicleOperationRequest(
                        rfid_uid=state['uid'],
                        idempotency_key=state['exit_key'],
                        source='simulation',
                    )
                )
                state.update(phase='departing', due=now + 18)
            else:
                route_id = f"parking-exit-{self.run_id}-{vehicle_id}"
                try:
                    connection.route.add(route_id, state['route'])
                    connection.vehicle.add(vehicle_id, route_id, depart='now')
                except Exception:
                    log.exception('Could not rejoin traffic for %s', vehicle_id)
                    continue
                self.completed.add(vehicle_id)
                del self.active[vehicle_id]
        admitted = 0
        for vehicle in vehicles:
            vehicle_id = vehicle['id']
            if vehicle['in_city'] or vehicle['on_ramp'] or vehicle_id in self.active or vehicle_id in self.completed:
                continue
            if admitted >= 2:
                break
            route = list(connection.vehicle.getRoute(vehicle_id))
            index = max(0, connection.vehicle.getRouteIndex(vehicle_id))
            route = route[index:]
            if not route:
                continue
            uid = _sumo_vehicle_uid(vehicle_id)
            try:
                result = self.parking.enter(
                    VehicleOperationRequest(
                        rfid_uid=uid,
                        idempotency_key=_sumo_operation_key(
                            self.run_id, vehicle_id, 'entry'
                        ),
                        source='simulation',
                    )
                )
            except Exception:
                log.exception('Parking admission failed for %s', vehicle_id)
                continue
            try:
                connection.vehicle.remove(vehicle_id)
            except Exception:
                self.parking.exit(
                    VehicleOperationRequest(
                        rfid_uid=uid,
                        idempotency_key=_sumo_operation_key(
                            self.run_id, vehicle_id, 'rollback'
                        ),
                        source='simulation',
                    )
                )
                continue
            floor = (
                int(result.slot_name.split('-')[0][1:])
                if result.slot_name.startswith('L')
                else 5
            )
            self.active[vehicle_id] = dict(
                uid=uid,
                slot_id=result.slot_id,
                phase='parked',
                due=now + 180 + result.slot_id % 120 + abs(floor - 3) * 120,
                route=route,
                exit_key=_sumo_operation_key(self.run_id, vehicle_id, 'exit'),
            )
            admitted += 1
        return [v for v in vehicles if v['id'] not in self.active]

    def close(self):
        # Recover sessions left by an interrupted native simulation as well.
        for slot in self.parking.status().slots:
            if slot.occupied and slot.rfid_uid and slot.rfid_uid.startswith('SUMO:'):
                try:
                    self.parking.exit(VehicleOperationRequest(rfid_uid=slot.rfid_uid, idempotency_key=f"sim-close:{slot.active_session_id}", source='simulation'))
                except Exception:
                    log.exception('Could not release simulation parking session %s', slot.id)
        self.active.clear()
