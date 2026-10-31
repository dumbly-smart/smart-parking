from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SimulatedVehicle(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    x: float
    y: float
    elevation: float = 0
    floor: int = Field(default=1, ge=1, le=6)
    road_id: str = ""
    in_city: bool = False
    on_ramp: bool = False
    speed_mps: float = Field(ge=0)
    angle: float

    @model_validator(mode="after")
    def finite_position(self) -> SimulatedVehicle:
        if not all(math.isfinite(value) for value in (self.x, self.y, self.elevation, self.speed_mps, self.angle)):
            raise ValueError("SUMO vehicle coordinates and motion must be finite")
        return self


class SumoStatusResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    available: bool
    state: Literal["stopped", "starting", "running", "paused", "unavailable", "error"]
    error: str | None = None
    simulation_time: float = Field(ge=0)
    vehicle_count: int = Field(ge=0)
    mean_speed_mps: float = Field(ge=0)
    vehicles: tuple[SimulatedVehicle, ...] = ()
    traffic_lights: dict[str, str] = Field(default_factory=dict)
    parking_vehicles: tuple[dict[str, Any], ...] = ()


class SumoMapResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1]
    type: Literal["garage-layout"]
    units: Literal["m"]
    reference: dict[str, Any]
    bounds: dict[str, float]
    outline: tuple[tuple[float, float], ...]
    reference_bays: tuple[dict[str, Any], ...]
    active_bays: tuple[dict[str, Any], ...]
    aisles: tuple[dict[str, Any], ...]
    ramps: tuple[dict[str, Any], ...]
    service_cores: tuple[dict[str, Any], ...]
    columns: tuple[dict[str, float], ...]
    network: dict[str, Any]
    zones: tuple[dict[str, Any], ...] = ()
    gates: tuple[dict[str, Any], ...] = ()
    city: dict[str, Any] = Field(default_factory=dict)
    floors: tuple[dict[str, Any], ...] = ()
    inter_floor_ramps: tuple[dict[str, Any], ...] = ()
    floor_height: float = Field(default=4.2, gt=0)
    ground_floor: int = Field(default=1, ge=1, le=6)
    tracked_floor: int = Field(default=5, ge=1, le=6)

    @model_validator(mode="after")
    def usable_garage_layout(self) -> SumoMapResponse:
        bound_keys = ("min_x", "max_x", "min_y", "max_y")
        if not all(key in self.bounds and math.isfinite(self.bounds[key]) for key in bound_keys):
            raise ValueError("garage bounds must be finite metre coordinates")
        if not (self.bounds["min_x"] < self.bounds["max_x"] and self.bounds["min_y"] < self.bounds["max_y"]):
            raise ValueError("garage bounds must describe a non-empty floor")
        if len(self.outline) < 4:
            raise ValueError("garage floor outline must contain at least four points")

        def validate_point(point: tuple[float, float]) -> None:
            if not all(math.isfinite(value) for value in point):
                raise ValueError("garage plan coordinates must be finite")
            if not (self.bounds["min_x"] <= point[0] <= self.bounds["max_x"] and self.bounds["min_y"] <= point[1] <= self.bounds["max_y"]):
                raise ValueError("garage plan coordinates must be inside the floor bounds")

        for point in self.outline:
            validate_point(point)
        for zone in self.zones:
            validate_point((float(zone["x"]), float(zone["y"])))
        for gate in self.gates:
            validate_point((float(gate["x"]), float(gate["y"])))
        if self.floors:
            numbers = [floor["number"] for floor in self.floors]
            if numbers != list(range(1, len(numbers) + 1)) or len(numbers) != 6:
                raise ValueError("multilevel garage must provide consecutive floors 1 through 6")
            for floor in self.floors:
                elevation = float(floor["elevation"])
                if not math.isfinite(elevation) or not math.isclose(elevation, (floor["number"] - self.ground_floor) * self.floor_height):
                    raise ValueError("floor elevations must match the declared floor height")
                if len(floor["bays"]) != floor["bay_count"]:
                    raise ValueError("floor bay count must match its modeled spaces")
                for bay in floor["bays"]:
                    validate_point((float(bay["x"]), float(bay["y"])))
                    if bay.get("live_slot_id") is not None and floor["number"] != self.tracked_floor:
                        raise ValueError("live bays must remain on the tracked floor")
            expected_links = {(level, level + 1) for level in range(1, 6)} | {(level + 1, level) for level in range(1, 6)}
            if {(r["from_floor"], r["to_floor"]) for r in self.inter_floor_ramps} != expected_links:
                raise ValueError("ramps must connect every adjacent floor in both directions")
            for ramp in self.inter_floor_ramps:
                if abs(ramp["from_floor"] - ramp["to_floor"]) != 1:
                    raise ValueError("inter-floor ramps must connect adjacent floors")
                for point in ramp["points"]:
                    validate_point((float(point[0]), float(point[1])))
                    if not math.isfinite(float(point[2])):
                        raise ValueError("ramp elevation must be finite")
                if len(ramp["points"]) < 2 or not math.isclose(ramp["points"][0][2], (ramp["from_floor"] - self.ground_floor) * self.floor_height) or not math.isclose(ramp["points"][-1][2], (ramp["to_floor"] - self.ground_floor) * self.floor_height):
                    raise ValueError("ramp endpoints must meet their connected decks")
        ids = set()
        for bay in (*self.reference_bays, *self.active_bays):
            bay_id = bay.get("id")
            if not isinstance(bay_id, (str, int)) or str(bay_id) in ids:
                raise ValueError("garage bay ids must be present and unique")
            ids.add(str(bay_id))
            validate_point((float(bay["x"]), float(bay["y"])))
        if len(self.active_bays) != 5 or len(self.reference_bays) + len(self.active_bays) != int(self.reference.get("source_bay_count", 0)):
            raise ValueError("garage map must preserve five tracked bays and its stated reference count")
        if int(self.reference.get("reference_bay_count", -1)) != len(self.reference_bays):
            raise ValueError("garage reference count must match the rendered context bays")
        if not self.aisles or not self.network.get("nodes") or not self.network.get("edges") or not self.network.get("routes"):
            raise ValueError("garage map must provide drive aisles and a SUMO road network")
        for aisle in self.aisles:
            points = aisle.get("points")
            if not isinstance(points, list) or len(points) < 2:
                raise ValueError("garage aisles need at least two local-coordinate points")
            for point in points:
                validate_point((float(point[0]), float(point[1])))
        return self
