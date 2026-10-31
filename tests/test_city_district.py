"""City geometry and SUMO share a connected, non-overlapping coordinate model."""
import json
from pathlib import Path

import pytest

from backend.app.models.sumo import SumoMapResponse


@pytest.fixture
def layout():
    return json.loads(Path('backend/app/static/data/haneda-p2-5f-layout.json').read_text())


def test_city_has_detailed_district_and_keeps_garage_geometry(layout):
    city = layout['city']
    assert city['fictional'] is True
    assert len(city['buildings']) >= 90
    assert len({b['style'] for b in city['buildings']}) >= 5
    assert len(city['roads']) >= 100
    assert len(city['signals']) >= 16
    assert len(layout['active_bays']) == 5
    assert layout['floors'][0]['elevation'] == -8.4
    assert SumoMapResponse.model_validate(layout).city['name'] == city['name']


def test_buildings_clear_road_corridors_and_garage(layout):
    city = layout['city']
    for b in city['buildings']:
        assert all(abs(b['x']-x) > b['width']/2+12 for x in city['grid_x'])
        assert all(abs(b['y']-y) > b['depth']/2+12 for y in city['grid_y'])
        assert abs(b['x'])-b['width']/2 > 118 or abs(b['y'])-b['depth']/2 > 62
        assert b['height'] > 0


def test_every_city_and_garage_route_is_connected(layout):
    edges = {e['id']:e for e in layout['network']['edges']}
    for route in layout['network']['routes']:
        path = [edges[e] for e in route['edges']]
        assert all(a['to']==b['from'] for a,b in zip(path,path[1:])), route['id']
    arrivals = [r for r in layout['network']['routes'] if r['id'].startswith('arrival_to_')]
    assert len(arrivals)==6
    for r in arrivals:
        assert r['edges'][0].startswith('city_')
        assert 'city_garage_in' in r['edges'] and 'street_in' in r['edges']
        assert 'city_garage_out' in r['edges']
        assert r['edges'][-1].startswith('city_')
    city_nodes = {n['id']:n for n in layout['network']['nodes'] if n['id'].startswith('C')}
    assert all(n['z']==0 for n in city_nodes.values())


def test_render_lanes_and_signals_export_native_sumo_indices(layout):
    city=layout['city'];edges={e['id']:e for e in layout['network']['edges']}
    for road in city['roads']:
        assert road['id'] in edges
        assert len(road['lanes'])==edges[road['id']]['lanes']
        assert all(len(lane['shape'])>=2 for lane in road['lanes'])
    for s in city['signals']:
        assert s['indices'] and min(s['indices'])>=0
        assert s['incoming_edge'] in edges


def test_central_landscaping_never_covers_native_sumo_lanes(layout):
    for plaza in layout['city']['plazas']:
        px0,px1=plaza['x']-plaza['width']/2,plaza['x']+plaza['width']/2
        py0,py1=plaza['y']-plaza['depth']/2,plaza['y']+plaza['depth']/2
        for road in layout['city']['roads']:
            for lane in road['lanes']:
                half=lane['width']/2
                for a,b in zip(lane['shape'],lane['shape'][1:]):
                    rx0,rx1=min(a[0],b[0])-half,max(a[0],b[0])+half
                    ry0,ry1=min(a[1],b[1])-half,max(a[1],b[1])+half
                    assert px1<=rx0 or px0>=rx1 or py1<=ry0 or py0>=ry1, (plaza,road['id'])
