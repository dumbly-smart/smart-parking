#!/usr/bin/env python3
"""Build the Haneda P2 5F garage model and its local-coordinate SUMO network."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

from garage_multilevel import add_multilevel
from city_district import add_city, export_city_network

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config/parking.yaml"
MAP_PATH = ROOT / "backend/app/static/data/haneda-p2-5f-layout.json"
OUT_DIR = ROOT / "data/sumo/haneda-p2"
SOURCE_URL = "https://www.aeif.or.jp/haneda/pdf/parking/p2/floor_p2.pdf"
FLOOR_PAGE_URL = f"{SOURCE_URL}#page=5"

FLOOR_BOUNDS = {"min_x": -95.0, "max_x": 95.0, "min_y": -32.0, "max_y": 32.0}

NETWORK_NODES = [
    {"id": "entry_ramp", "x": 22, "y": 0},
    {"id": "entry_merge", "x": 22, "y": -8},
    {"id": "east_gap_north", "x": 40, "y": -8},
    {"id": "east_gap_south", "x": 40, "y": -20},
    {"id": "east_south", "x": 78, "y": -20},
    {"id": "east_north", "x": 78, "y": 20},
    {"id": "north_center", "x": 18, "y": 20},
    {"id": "west_north", "x": -83, "y": 20},
    {"id": "west_south", "x": -83, "y": -20},
    {"id": "south_center", "x": -8, "y": -20},
    {"id": "exit_merge", "x": -8, "y": 4},
    {"id": "exit_ramp", "x": -8, "y": 10},
]
NETWORK_EDGES = [
    {"id": "up_ramp", "from": "entry_ramp", "to": "entry_merge", "speed": 4.0, "kind": "ramp"},
    {"id": "ramp_connector", "from": "entry_merge", "to": "east_gap_north", "speed": 4.5, "kind": "aisle"},
    {"id": "east_gap_connector", "from": "east_gap_north", "to": "east_gap_south", "speed": 4.5, "kind": "aisle"},
    {"id": "south_link", "from": "east_gap_south", "to": "east_south", "speed": 6.0, "kind": "aisle"},
    {"id": "east_spine", "from": "east_south", "to": "east_north", "speed": 4.5, "kind": "aisle"},
    {"id": "north_aisle", "from": "east_north", "to": "north_center", "speed": 6.0, "kind": "aisle"},
    {"id": "north_west_aisle", "from": "north_center", "to": "west_north", "speed": 6.0, "kind": "aisle"},
    {"id": "west_spine", "from": "west_north", "to": "west_south", "speed": 4.5, "kind": "aisle"},
    {"id": "south_to_down", "from": "west_south", "to": "south_center", "speed": 6.0, "kind": "aisle"},
    {"id": "south_to_east", "from": "south_center", "to": "east_south", "speed": 6.0, "kind": "aisle"},
    {"id": "down_connector", "from": "south_center", "to": "exit_merge", "speed": 4.5, "kind": "aisle"},
    {"id": "down_ramp", "from": "exit_merge", "to": "exit_ramp", "speed": 4.0, "kind": "ramp"},
]
NETWORK_ROUTES = [
    {"id": "through_flow", "edges": ["up_ramp", "ramp_connector", "east_gap_connector", "south_link", "east_spine", "north_aisle", "north_west_aisle", "west_spine", "south_to_down", "down_connector", "down_ramp"], "period": 2.6, "begin": 0},
    {"id": "full_floor_loop", "edges": ["up_ramp", "ramp_connector", "east_gap_connector", "south_link", "east_spine", "north_aisle", "north_west_aisle", "west_spine", "south_to_down", "south_to_east", "east_spine", "north_aisle", "north_west_aisle", "west_spine", "south_to_down", "down_connector", "down_ramp"], "period": 6.5, "begin": 1},
    {"id": "west_search", "edges": ["up_ramp", "ramp_connector", "east_gap_connector", "south_link", "east_spine", "north_aisle", "north_west_aisle", "west_spine", "south_to_down", "down_connector", "down_ramp"], "period": 8.5, "begin": 2.4},
]


def configured_slots() -> list[dict[str, Any]]:
    parking = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    result = []
    for slot in parking["slots"]:
        point = slot["scene"]["position"]
        result.append({
            "id": slot["id"],
            "name": slot["name"],
            "source_id": slot["name"],
            "x": float(point["x"]),
            "y": -float(point["z"]),
            "orientation": "north-south",
        })
    return result


def layout_data() -> dict[str, Any]:
    active = configured_slots()
    active_source_ids = {slot["source_id"] for slot in active}
    all_bays: list[dict[str, Any]] = []

    def add_bay(zone: str, x: float, y: float, orientation: str, group: str) -> None:
        all_bays.append({
            "id": f"ref-{len(all_bays) + 1:03}",
            "zone": zone,
            "x": round(x, 3),
            "y": round(y, 3),
            "orientation": orientation,
            "group": group,
        })

    def horizontal_row(zone: str, count: int, start_x: float, y: float, group: str) -> None:
        for index in range(count):
            source_id = f"{zone}{501 + index}"
            if source_id in active_source_ids:
                continue
            add_bay(zone, start_x + index * 2.5, y, "north-south", group)

    def vertical_bank(zone: str, count: int, center_x: float, group: str) -> None:
        per_row = count // 2
        y_start = -(per_row - 1) * 1.25
        for row_x in (center_x - 4.9, center_x + 4.9):
            for index in range(per_row):
                add_bay(zone, row_x, y_start + index * 2.5, "east-west", group)

    # Outer rows and the right-side numbered run follow the official 5F plan's
    # orientation.  S501-S505 remain the configured/live spaces from parking.yaml.
    horizontal_row("S", 35, -86.25, 26.5, "north-perimeter")
    horizontal_row("E", 35, 1.25, 26.5, "north-perimeter")
    horizontal_row("H", 18, -82.5, -26.5, "south-perimeter")
    horizontal_row("G", 22, -26.25, -26.5, "south-perimeter")
    horizontal_row("A", 16, 48.75, -26.5, "south-perimeter")
    for index in range(18):
        add_bay("D", 90, -21.25 + index * 2.5, "east-west", "east-perimeter")

    for zone, center_x in zip(("R", "N", "M", "L", "K", "J"), (-83, -68, -53, -38, -23, -8), strict=True):
        vertical_bank(zone, 26, center_x, "west-double-loaded")
    for zone, center_x, count in (("B", 48, 26), ("C", 63, 26), ("D", 78, 16)):
        vertical_bank(zone, count, center_x, "east-double-loaded")

    # Short E and G banks sit beyond the up/down loop; their positions leave the
    # north/south circulation lanes clear.  Together they model the ramp-side
    # stalls shown in the published central section.
    for index in range(14):
        add_bay("E", 2.5 + index * 2.5, 13.0, "north-south", "ramp-north-bank")
        add_bay("G", 2.5 + index * 2.5, -13.0, "north-south", "ramp-south-bank")

    if len(all_bays) + len(active) != 396:
        raise ValueError(f"expected 396 mapped spaces including live bays, got {len(all_bays) + len(active)}")

    zones = [
        {"id": "A", "x": 67, "y": -23}, {"id": "B", "x": 48, "y": 15},
        {"id": "C", "x": 63, "y": 15}, {"id": "D", "x": 86, "y": 23},
        {"id": "E", "x": 19, "y": 17}, {"id": "F", "x": 13, "y": 0},
        {"id": "G", "x": 19, "y": -17}, {"id": "H", "x": -62, "y": -23},
        {"id": "J", "x": -8, "y": 17}, {"id": "K", "x": -23, "y": 17},
        {"id": "L", "x": -38, "y": 17}, {"id": "M", "x": -53, "y": 17},
        {"id": "N", "x": -68, "y": 17}, {"id": "R", "x": -83, "y": 17},
        {"id": "S", "x": -48, "y": 30},
    ]
    columns = [
        {"x": x, "y": y}
        for x in (-89, -75, -60, -45, -30, -15, 0, 15, 30, 45, 60, 75, 89)
        for y in (-20, 0, 20)
    ]

    return {
        "schema_version": 1,
        "type": "garage-layout",
        "units": "m",
        "reference": {
            "name": "Haneda Airport P2 Parking Garage",
            "level": "5F · reserved-car floor",
            "source_url": SOURCE_URL,
            "source_floor_url": FLOOR_PAGE_URL,
            "source_page": 5,
            "facility_capacity": 2315,
            "floor_capacity": 396,
            "source_bay_count": 396,
            "tracked_bay_count": len(active),
            "reference_bay_count": len(all_bays),
            "attribution": "Official P2 floor-map PDF, page 5. The operator lists 2,315 total spaces and the full 5F as a 396-space reservation level.",
            "note": "The local-coordinate 3D geometry is a visual reconstruction of the official full-floor guide, not a surveyed/as-built plan. The five tracked spaces are mapped to the S501-S505 positions; remaining spaces are rendered as layout context only.",
        },
        "bounds": FLOOR_BOUNDS,
        "outline": [
            [-90, -32], [-93, -30], [-94, -27], [-94, 27], [-92, 30],
            [-88, 31], [88, 31], [92, 30], [94, 27], [94, -27],
            [92, -30], [88, -31], [-88, -31], [-92, -30],
        ],
        "reference_bays": all_bays,
        "active_bays": active,
        "zones": zones,
        "aisles": [
            {"id": "north-main", "name": "North circulation aisle", "width": 5.2, "points": [[-89, 20], [-25, 20], [8, 20], [78, 20]], "kind": "drive"},
            {"id": "south-main", "name": "South circulation aisle", "width": 5.2, "points": [[-83, -20], [-25, -20], [8, -20], [78, -20]], "kind": "drive"},
            {"id": "west-spine", "name": "West return aisle", "width": 4.6, "points": [[-83, -20], [-83, 20]], "kind": "drive"},
            {"id": "east-spine", "name": "East return aisle", "width": 4.6, "points": [[78, -20], [78, 20]], "kind": "drive"},
            {"id": "ramp-loop", "name": "5F up/down ramp circulation", "width": 4.8, "points": [[22, -8], [26, -4], [26, 4], [22, 8], [-8, 8], [-8, -8], [22, -8]], "kind": "drive"},
            *[
                {"id": f"zone-aisle-{zone}", "name": f"Zone {zone} parking aisle", "width": 4.8, "points": [[x, -20 if zone == "J" else -17], [x, -8 if zone == "J" else 17]], "kind": "drive"}
                for zone, x in (("N", -68), ("M", -53), ("L", -38), ("K", -23), ("J", -8), ("B", 48), ("C", 63))
            ],
            {"id": "ramp-access", "name": "East ramp access aisle", "width": 3.6, "points": [[22, -8], [40, -8], [40, -20]], "kind": "drive"},
        ],
        "ramps": [
            {"id": "up", "name": "UP · from 4F", "points": [[22, -8], [22, -3]]},
    {"id": "down", "name": "DOWN · to 4F", "points": [[-8, 4], [-8, 10]]},
        ],
        "gates": [
            {"operation": "entry", "x": 22, "y": -5, "axis": "x"},
            {"operation": "exit", "x": -8, "y": 7, "axis": "x"},
        ],
        "service_cores": [
            {"id": "ramp-core", "name": "UP / DOWN RAMP", "x": 7, "y": 0, "width": 22, "depth": 6},
            {"id": "lift-b", "name": "ELEVATOR HALL B", "x": -33, "y": -28, "width": 8, "depth": 6},
            {"id": "lift-a", "name": "ELEVATOR HALL A", "x": 37, "y": -28, "width": 8, "depth": 6},
        ],
        "columns": columns,
        "network": {"nodes": NETWORK_NODES, "edges": NETWORK_EDGES, "routes": NETWORK_ROUTES},
    }


def locate_netconvert() -> str:
    found = shutil.which("netconvert")
    if found:
        return found
    try:
        import sumo

        candidate = Path(sumo.__file__).resolve().parent / "bin/netconvert"
        if candidate.is_file():
            return str(candidate)
    except ImportError:
        pass
    candidate = Path(sys.executable).parent / "netconvert"
    if candidate.is_file():
        return str(candidate)
    raise RuntimeError("netconvert was not found. Install SUMO or add its bin directory to PATH.")


def write_network(layout: dict[str, Any], staging_dir: Path, end: int) -> None:
    node_path = staging_dir / "garage.nod.xml"
    edge_path = staging_dir / "garage.edg.xml"
    net_path = staging_dir / "garage.net.xml"
    route_path = staging_dir / "garage.rou.xml"
    config_path = staging_dir / "garage.sumocfg"
    nodes = ["<nodes>"]
    for node in layout["network"]["nodes"]:
        nodes.append(f'<node id="{node["id"]}" x="{node["x"]}" y="{node["y"]}" z="{node.get("z", 0)}" type="{node.get("type", "priority")}"/>')
    nodes.append("</nodes>")
    node_path.write_text("\n".join(nodes) + "\n", encoding="utf-8")
    edges = ["<edges>"]
    for edge in layout["network"]["edges"]:
        shape = " ".join(",".join(str(value) for value in point) for point in edge.get("shape", []))
        shape_attribute = f' shape="{shape}"' if shape else ""
        edges.append(
            f'<edge id="{edge["id"]}" from="{edge["from"]}" to="{edge["to"]}" '
            f'numLanes="{edge.get("lanes", 1)}" width="{edge.get("width", 3.2)}" spreadType="{edge.get("spread", "center")}" speed="{edge["speed"]}" priority="3"{shape_attribute}/>'
        )
    edges.append("</edges>")
    edge_path.write_text("\n".join(edges) + "\n", encoding="utf-8")
    subprocess.run(
        [locate_netconvert(), "--node-files", str(node_path), "--edge-files", str(edge_path), "--output-file", str(net_path), "--no-turnarounds", "true", "--offset.disable-normalization"],
        check=True,
    )
    if layout.get("city"):
        export_city_network(layout, net_path)
    routes = [
        "<routes>",
        '<vType id="passenger" vClass="passenger" length="4.6" width="1.8" accel="2.6" decel="4.5" maxSpeed="13.9" sigma="0.25" color="0.24,0.73,0.82"/>',
    ]
    for route in sorted(layout["network"]["routes"], key=lambda route: route["begin"]):
        routes.append(f'<route id="{route["id"]}" edges="{" ".join(route["edges"])}"/>')
        routes.append(
            f'<flow id="flow-{route["id"]}" type="passenger" route="{route["id"]}" '
            f'begin="{route["begin"]}" end="{end}" period="{route["period"]}" '
            'departLane="best" departSpeed="max"/>'
        )
    routes.append("</routes>")
    route_path.write_text("\n".join(routes) + "\n", encoding="utf-8")
    config_path.write_text(
        "<configuration><input>"
        '<net-file value="garage.net.xml"/><route-files value="garage.rou.xml"/>'
        "</input><time>"
        f'<begin value="0"/><end value="{end}"/><step-length value="0.25"/>'
        "</time><processing><time-to-teleport value=\"-1\"/></processing></configuration>\n",
        encoding="utf-8",
    )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for filename in ("garage.net.xml", "garage.rou.xml", "garage.sumocfg"):
        os.replace(staging_dir / filename, OUT_DIR / filename)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--end", type=int, default=3600, help="simulation horizon in seconds")
    args = parser.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    layout = add_city(add_multilevel(layout_data()))
    with tempfile.TemporaryDirectory(prefix="garage-build-", dir=OUT_DIR) as staging_name:
        staging = Path(staging_name)
        write_network(layout, staging, args.end)
        staged_map = staging / MAP_PATH.name
        staged_map.write_text(json.dumps(layout, separators=(",", ":")), encoding="utf-8")
        os.replace(staged_map, MAP_PATH)
    print(f"Haneda P2 model: {len(layout['floors'])} decks, {len(layout['inter_floor_ramps'])} connecting ramps, {len(layout['active_bays'])} monitored bays → {MAP_PATH}")
    print(f"SUMO network: {OUT_DIR / 'garage.sumocfg'}")
    print(f"Official full-floor guide: {FLOOR_PAGE_URL}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.CalledProcessError, RuntimeError, yaml.YAMLError, KeyError, TypeError, ValueError) as error:
        raise SystemExit(f"Haneda P2 garage build failed: {error}") from error
