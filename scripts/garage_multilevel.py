"""Build an emulated six-deck facility with physically elevated SUMO ramps."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

FLOOR_HEIGHT = 4.2
FLOOR_COUNT = 6
GROUND_FLOOR = 3
FLOOR_NAMES = ["B2", "B1", "G", "1F", "2F", "3F / ROOF"]
FLOOR_COLORS = ["#76c8d4", "#f0a377", "#bf9bdb", "#efc66a", "#e58dba", "#a9d47c"]


def add_multilevel(layout: dict[str, Any]) -> dict[str, Any]:
    layout = deepcopy(layout)
    template = [*layout["reference_bays"], *layout["active_bays"]]
    layout["floor_height"] = FLOOR_HEIGHT
    layout["tracked_floor"] = 5
    layout["ground_floor"] = GROUND_FLOOR
    layout["floors"] = []
    for level in range(1, FLOOR_COUNT + 1):
        bays = [{**bay, "id": f"L{level}-{index:03}", "live_slot_id": bay["id"] if level == 5 and isinstance(bay["id"], int) else None} for index, bay in enumerate(template)]
        layout["floors"].append({
            "number": level, "name": FLOOR_NAMES[level - 1], "elevation": (level - GROUND_FLOOR) * FLOOR_HEIGHT, "underground": level < GROUND_FLOOR,
            "color": FLOOR_COLORS[level - 1], "bay_count": len(bays), "bays": bays,
            "source_page": level, "layout_basis": "5F reference template emulation" if level != 5 else "5F reference reconstruction",
        })
    for bay in layout["active_bays"]:
        bay.update(floor=5, elevation=(5 - GROUND_FLOOR) * FLOOR_HEIGHT)
    layout["reference"].update(
        level="B2 · B1 · G · 1F · 2F · 3F / roof · emulation", modeled_bay_count=sum(f["bay_count"] for f in layout["floors"]),
        note="Two basement and four above-ground modeled decks use the 5F reference template. Modeled bay counts and 4.2 m floor spacing are emulation parameters, distinct from the operator's 2,315-space facility count. Only five project bays on modeled 2F report live occupancy.",
    )
    layout["bounds"] = {"min_x": -112.0, "max_x": 100.0, "min_y": -56.0, "max_y": 36.0}
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    ramps: list[dict[str, Any]] = []
    node_lookup: dict[str, dict[str, Any]] = {}

    def node(name: str, x: float, y: float, z: float) -> str:
        item = {"id": name, "x": x, "y": y, "z": z}
        nodes.append(item)
        node_lookup[name] = item
        return name

    def edge(name: str, start: str, end: str, kind: str = "aisle", shape: list[list[float]] | None = None) -> str:
        a, b = node_lookup[start], node_lookup[end]
        points = shape or [[a["x"], a["y"], a["z"]], [b["x"], b["y"], b["z"]]]
        edges.append({"id": name, "from": start, "to": end, "speed": 3.5 if kind == "ramp" else 5.5, "kind": kind, "shape": points})
        return name

    for level in range(1, FLOOR_COUNT + 1):
        z = (level - GROUND_FLOOR) * FLOOR_HEIGHT
        for name, x, y in [("a", -35, -20), ("f", 35, -20), ("b", 78, -20), ("c", 78, 20), ("d", -83, 20), ("e", -83, -20), ("us", -35, -40), ("ue", 35, -40), ("ds", 35, -47), ("de", -35, -47)]:
            if level == 5 and name in {"c", "d"}:
                y = 21.6  # Entry lane clears the live-zone center-divider cabinet.
            node(f"L{level}_{name}", x, y, z)
        for start, end in [("e", "a"), ("a", "f"), ("f", "b"), ("b", "c"), ("c", "d"), ("d", "e")]:
            edge(f"L{level}_{start}_{end}", f"L{level}_{start}", f"L{level}_{end}")
        if level < FLOOR_COUNT:
            edge(f"L{level}_to_up", f"L{level}_a", f"L{level}_us")
            edge(f"L{level}_from_down", f"L{level}_de", f"L{level}_a")
        if level > 1:
            edge(f"L{level}_from_up", f"L{level}_ue", f"L{level}_f")
            edge(f"L{level}_to_down", f"L{level}_f", f"L{level}_ds")

    for lower in range(1, FLOOR_COUNT):
        upper = lower + 1
        for name, start, end, direction in [
            (f"up_{lower}_{upper}", f"L{lower}_us", f"L{upper}_ue", "up"),
            (f"down_{upper}_{lower}", f"L{upper}_ds", f"L{lower}_de", "down"),
        ]:
            edge(name, start, end, "ramp")
            ramps.append({"id": name, "direction": direction, "from_floor": lower if direction == "up" else upper, "to_floor": upper if direction == "up" else lower, "width": 3.8, "points": edges[-1]["shape"]})

    node("street_entry", -110, -20, 0)
    node("street_exit", -110, -28, 0)
    edge("street_in", "street_entry", "L3_e")
    edge("street_out", "L3_a", "street_exit", shape=[[-35, -20, 0], [-43, -28, 0], [-110, -28, 0]])

    def circuit(level: int) -> list[str]:
        return [f"L{level}_{a}_{b}" for a, b in [("f", "b"), ("b", "c"), ("c", "d"), ("d", "e"), ("e", "a")]]

    def travel(start: int, target: int) -> list[str]:
        # Every leg starts and ends at deck anchor a; all transitions are real ramps.
        result = []
        if target > start:
            for lower in range(start, target):
                high = lower + 1
                result += [f"L{lower}_to_up", f"up_{lower}_{high}", f"L{high}_from_up", *circuit(high)]
        else:
            for high in range(start, target, -1):
                result += [f"L{high}_a_f", f"L{high}_to_down", f"down_{high}_{high-1}", f"L{high-1}_from_down"]
        return result

    routes = []
    for target in range(1, FLOOR_COUNT + 1):
        tour = [f"L{target}_a_f", *circuit(target)]
        path = ["street_in", "L3_e_a", *travel(GROUND_FLOOR, target), *tour, *travel(target, GROUND_FLOOR), "street_out"]
        routes.append({"id": f"arrival_to_{target}F", "edges": path, "period": 24 + target * 3, "begin": target * .6})
        warm = [*circuit(target), *travel(target, GROUND_FLOOR), "street_out"]
        routes.append({"id": f"departure_from_{target}F", "edges": warm, "period": 24 + target * 4, "begin": target * .2})
    layout["network"] = {"nodes": nodes, "edges": edges, "routes": routes}
    layout["inter_floor_ramps"] = ramps
    return layout
