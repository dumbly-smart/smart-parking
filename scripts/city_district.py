"""Deterministic fictional city, connected to the garage in native SUMO coordinates."""
from __future__ import annotations

from collections import deque
import random
from typing import Any
import xml.etree.ElementTree as ET

GRID_X = [-560, -360, -160, 160, 360, 560]
GRID_Y = [-540, -340, -140, 140, 340, 540]


def add_city(layout: dict[str, Any]) -> dict[str, Any]:
    network = layout['network']
    nodes, edges = network['nodes'], network['edges']
    lookup = {n['id']:n for n in nodes}
    city_edges = []

    def node(name, x, y, signal=False):
        item = dict(id=name,x=x,y=y,z=0,type='traffic_light' if signal else 'priority')
        nodes.append(item);lookup[name]=item

    def edge(a, b, name=None, lanes=2):
        item=dict(id=name or f'city_{a}_{b}', **{'from':a,'to':b},speed=11.1,kind='city',lanes=lanes,width=3.2,spread='right',shape=[[lookup[k]['x'],lookup[k]['y'],0] for k in (a,b)])
        edges.append(item);city_edges.append(item)

    for i,x in enumerate(GRID_X):
        for j,y in enumerate(GRID_Y):
            node(f'C{i}_{j}',x,y,0<i<5 and 0<j<5)
    node('C_access',-160,-20)
    for i in range(6):
        for j in range(6):
            for ni,nj in [(i+1,j),(i,j+1)]:
                if ni>5 or nj>5:continue
                chain=[f'C{i}_{j}',f'C{ni}_{nj}']
                if (i,j,ni,nj)==(2,2,2,3):chain.insert(1,'C_access')
                for a,b in zip(chain,chain[1:]):edge(a,b);edge(b,a)
    edge('C_access','street_entry','city_garage_in',1)
    edge('street_exit','C_access','city_garage_out',1)
    # Separate outbound connector from the inbound carriageway at the gate.
    city_edges[-1]['shape']=[[-110,-28,0],[-138,-28,0],[-160,-20,0]]
    city_edges[-1]['spread']='center'
    city_edges[-2]['spread']='center'

    adjacency={}
    for e in city_edges:adjacency.setdefault(e['from'],[]).append(e)

    def path(start, end):
        queue=deque([(start,[]) ]);seen={start}
        while queue:
            at,route=queue.popleft()
            if at==end:return route
            for e in adjacency.get(at,[]):
                if e['to'] not in seen:
                    seen.add(e['to']);queue.append((e['to'],route+[e['id']]))
        raise ValueError(f'No city path {start} → {end}')

    for index,r in enumerate(network['routes']):
        if r['id'].startswith('arrival_to_'):
            origin=['C0_2','C2_0','C0_3'][index%3]
            r['edges']=path(origin,'street_entry')+r['edges']
        r['edges']+=path('street_exit',['C5_2','C2_5','C0_4'][index%3])
    through=[]
    for row in [1,2,3,4]:
        through.extend([(f'C0_{row}',f'C5_{row}'),(f'C5_{row}',f'C0_{row}')])
    for col in [1,2,3,4]:
        through.extend([(f'C{col}_0',f'C{col}_5'),(f'C{col}_5',f'C{col}_0')])
    for index,(a,b) in enumerate(through):
        network['routes'].append(dict(id=f'city_through_{index}',edges=path(a,b),period=22+index%4*3,begin=index*.8))

    rng=random.Random(20261027);buildings=[];blocks=[]
    styles=['office','apartment','brick','hotel','retail','tower']
    colors=['#d4c6b0','#b6c6cd','#b7d2ca','#b38470','#e0c4a0','#899eaf','#d1b1bd','#88a6ad']
    for i,(left,right) in enumerate(zip(GRID_X,GRID_X[1:])):
        for j,(bottom,top) in enumerate(zip(GRID_Y,GRID_Y[1:])):
            blocks.append(dict(x=(left+right)/2,y=(bottom+top)/2,width=right-left-22,depth=top-bottom-22,park=(i,j)==(3,1),central=(i,j)==(2,2)))
            if (i,j) in {(2,2),(3,1)}:continue
            cols=3 if right-left>250 else 2;rows=2
            cellw=(right-left-52)/cols;celld=(top-bottom-52)/rows
            for col in range(cols):
                for row in range(rows):
                    style=styles[(i*3+j+col+row)%len(styles)]
                    h=rng.randint(5,14)*3.5 if style not in {'retail','tower'} else rng.randint(2,4)*4 if style=='retail' else rng.randint(18,26)*3.6
                    buildings.append(dict(id=f'block-{i}-{j}-{col}-{row}',x=left+26+cellw*(col+.5),y=bottom+26+celld*(row+.5),width=cellw-rng.randint(9,17),depth=celld-rng.randint(9,17),height=h,style=style,color=rng.choice(colors),accent=rng.choice(['#409a9e','#d59a55','#c57268','#6b85b4']),seed=len(buildings)))
    buildings.append(dict(id='central-mall',x=35,y=101,width=156,depth=43,height=17,style='mall',color='#e5d7bc',accent='#d89a62',seed=901))
    layout['city']=dict(name='Parkflow Central District',fictional=True,units='m',bounds=dict(min_x=-640,max_x=640,min_y=-620,max_y=620),grid_x=GRID_X,grid_y=GRID_Y,blocks=blocks,buildings=buildings,plazas=[dict(x=0,y=104,width=275,depth=42,surface='paving'),dict(x=0,y=-111,width=272,depth=28,surface='grass')],roads=[],signals=[],junctions=[],description='Fictional city geometry with native SUMO roads and traffic signals; the garage retains its reference-based emulated layout.')
    return layout


def export_city_network(layout: dict[str, Any], net_path) -> None:
    """Use compiled lane geometry and controlled-link indices, never guessed offsets."""
    net=ET.parse(net_path).getroot();city=layout['city']
    definitions={e['id']:e for e in layout['network']['edges'] if e.get('kind')=='city'}
    lanes={}
    for edge in net.findall('edge'):
        if edge.get('id') not in definitions:continue
        exported=[]
        for lane in edge.findall('lane'):
            shape=[[float(v) for v in p.split(',')] for p in lane.get('shape').split()]
            item=dict(id=lane.get('id'),width=float(lane.get('width','3.2')),shape=shape)
            exported.append(item);lanes[item['id']]=item
        city['roads'].append(dict(id=edge.get('id'),lanes=exported))
    for junction in net.findall('junction'):
        if junction.get('id','').startswith('C'):
            city['junctions'].append(dict(id=junction.get('id'),x=float(junction.get('x')),y=float(junction.get('y')),shape=[[float(v) for v in p.split(',')] for p in junction.get('shape','').split()]))
    heads={}
    for connection in net.findall('connection'):
        tl=connection.get('tl');incoming=connection.get('from')
        if not tl or incoming not in definitions:continue
        key=(tl,incoming);head=heads.setdefault(key,dict(id=f'{tl}:{incoming}',controller=tl,incoming_edge=incoming,indices=[],lane=lanes[f'{incoming}_{connection.get("fromLane")}']))
        head['indices'].append(int(connection.get('linkIndex')))
        if connection.get('dir')=='s':head.setdefault('straight',[]).append(int(connection.get('linkIndex')))
    city['signals']=[{**h,'indices':sorted(set(h.get('straight',h['indices'])))} for h in heads.values()]
