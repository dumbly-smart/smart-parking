"""Contract checks for physically connected multi-deck SUMO rendering."""
import copy
import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.models.sumo import SimulatedVehicle, SumoMapResponse


@pytest.fixture
def layout():
    return json.loads(Path('backend/app/static/data/haneda-p2-5f-layout.json').read_text())


def test_all_arrival_routes_connect_street_to_all_six_elevations(layout):
    edges = {edge['id']: edge for edge in layout['network']['edges']}
    nodes = {node['id']: node for node in layout['network']['nodes']}
    for route in layout['network']['routes']:
        path = [edges[edge_id] for edge_id in route['edges']]
        assert all(a['to'] == b['from'] for a, b in zip(path, path[1:]))
        assert path[-1]['to'].startswith('C')
        if route['id'].startswith('arrival_to_'):
            target = int(route['id'].split('_')[-1][0])
            assert path[0]['from'].startswith('C')
            assert any(math.isclose(nodes[edge['to']]['z'], (target - layout['ground_floor']) * 4.2) for edge in path)
            assert nodes[path[0]['from']]['z'] == 0
            assert nodes[path[-1]['to']]['z'] == 0


def test_ramps_have_drivable_gradient_and_match_rendered_decks(layout):
    model = SumoMapResponse.model_validate(layout)
    assert len(model.floors) == 6
    assert len(model.inter_floor_ramps) == 10
    for ramp in model.inter_floor_ramps:
        a, b = ramp['points'][0], ramp['points'][-1]
        gradient = abs(b[2] - a[2]) / math.hypot(b[0] - a[0], b[1] - a[1])
        assert 0 < gradient <= .12
        assert math.isclose(abs(b[2] - a[2]), model.floor_height)
    tracked = [(floor['number'], bay['live_slot_id']) for floor in model.floors for bay in floor['bays'] if bay.get('live_slot_id') is not None]
    assert tracked == [(5, slot) for slot in range(1, 6)]


@pytest.mark.parametrize('corruption', ['floor_elevation', 'ramp_endpoint', 'missing_ramp', 'nested_position'])
def test_map_contract_rejects_broken_multilevel_geometry(layout, corruption):
    bad = copy.deepcopy(layout)
    if corruption == 'floor_elevation':
        bad['floors'][2]['elevation'] = float('nan')
    elif corruption == 'ramp_endpoint':
        bad['inter_floor_ramps'][0]['points'][-1][2] = 99
    elif corruption == 'missing_ramp':
        bad['inter_floor_ramps'].pop()
    else:
        bad['floors'][1]['bays'][0]['x'] = float('inf')
    with pytest.raises(ValidationError):
        SumoMapResponse.model_validate(bad)


def test_vehicle_contract_preserves_fractional_ramp_elevation():
    car = SimulatedVehicle(id='ramp-car', x=1, y=2, elevation=6.3, floor=3, on_ramp=True, road_id='up_2_3', speed_mps=3, angle=90)
    assert car.model_dump()['elevation'] == 6.3
    with pytest.raises(ValidationError):
        SimulatedVehicle(id='bad', x=1, y=2, elevation=float('nan'), speed_mps=3, angle=0)


def test_basements_and_ground_access_share_simulation_elevations(layout):
    assert layout['ground_floor'] == 3
    assert [f['name'] for f in layout['floors']][:3] == ['B2', 'B1', 'G']
    assert [f['elevation'] for f in layout['floors']] == pytest.approx([-8.4, -4.2, 0, 4.2, 8.4, 12.6])
    edges = {e['id']: e for e in layout['network']['edges']}
    assert edges['street_in']['to'] == 'L3_e'
    assert edges['street_out']['from'] == 'L3_a'
    for floor in layout['floors']:
        assert floor['underground'] == (floor['elevation'] < 0)
    assert all(b['elevation'] == pytest.approx(8.4) for b in layout['active_bays'])
