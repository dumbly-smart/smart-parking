from __future__ import annotations

import importlib
import importlib.util
import os
import shutil
import socket
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any


class SumoService:
    """Own one optional SUMO process and publish a compact geographic snapshot."""

    def __init__(self, binary: str, config_path: Path, step_length: float, *, ground_floor: int = 1, floor_height: float = 4.2) -> None:
        self.binary = binary
        self.config_path = config_path
        self.step_length = step_length
        self.ground_floor = ground_floor
        self.floor_height = floor_height
        self._operation_lock = threading.RLock()
        self._lock = threading.RLock()
        self._worker: threading.Thread | None = None
        self._worker_stop: threading.Event | None = None
        self._connection: Any = None
        self._process: subprocess.Popen[Any] | None = None
        self.parking_traffic = None
        self._state = "stopped"
        self._error: str | None = None
        self._ready = False
        self._snapshot: dict[str, Any] = self._empty_snapshot()
        try:
            if not self.config_path.is_file():
                raise RuntimeError("Garage SUMO network is not built. Run `python scripts/build_select_citywalk_garage.py`.")
            self._binary_path()
            self._load_traci()
            self._ready = True
        except Exception as error:
            self._state = "unavailable"
            self._error = str(error)

    @staticmethod
    def _empty_snapshot() -> dict[str, Any]:
        return {"simulation_time": 0.0, "vehicle_count": 0, "mean_speed_mps": 0.0, "vehicles": []}

    def _load_traci(self) -> Any:
        sumo_home = os.environ.get("SUMO_HOME")
        if sumo_home:
            tools_path = str(Path(sumo_home) / "tools")
            if tools_path not in sys.path:
                sys.path.append(tools_path)
        if importlib.util.find_spec("traci") is None:
            raise RuntimeError("TraCI Python package is missing. Install SUMO or run `pip install traci`.")
        return importlib.import_module("traci")

    def _binary_path(self) -> str:
        candidate = Path(self.binary).expanduser()
        resolved = str(candidate) if candidate.is_file() else shutil.which(self.binary)
        if not resolved:
            venv_binary = Path(sys.executable).parent / self.binary
            if venv_binary.is_file():
                resolved = str(venv_binary)
        if not resolved:
            raise RuntimeError(f"SUMO binary '{self.binary}' was not found on PATH.")
        # The PyPI SUMO wheel installs a Python launcher in .venv/bin/sumo. Spawn
        # its bundled ELF executable directly so terminating our child also
        # terminates the actual simulator instead of orphaning a grandchild.
        resolved_path = Path(resolved)
        try:
            is_native_binary = resolved_path.read_bytes()[:4] == b"\x7fELF"
        except OSError:
            is_native_binary = True
        if not is_native_binary:
            sumo_spec = importlib.util.find_spec("sumo")
            if sumo_spec and sumo_spec.origin:
                bundled_binary = Path(sumo_spec.origin).parent / "bin" / "sumo"
                if bundled_binary.is_file():
                    resolved = str(bundled_binary)
        return resolved

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {"available": self._ready, "state": self._state, "error": self._error, **self._snapshot}

    def start(self) -> dict[str, Any]:
        with self._operation_lock:
            with self._lock:
                if self._state in {"running", "paused", "starting"}:
                    return self.status()
                self._state = "starting"
                self._error = None
            process: subprocess.Popen[Any] | None = None
            connection: Any = None
            try:
                if not self.config_path.is_file():
                    raise RuntimeError(
                        f"Garage SUMO network is not built yet. Run `python scripts/build_select_citywalk_garage.py` "
                        f"to create {self.config_path}."
                    )
                traci = self._load_traci()
                with socket.socket() as probe:
                    probe.bind(("127.0.0.1", 0))
                    port = probe.getsockname()[1]
                process = subprocess.Popen(
                    [self._binary_path(), "-c", str(self.config_path), "--step-length", str(self.step_length), "--remote-port", str(port)],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                connection = traci.connect(
                    port=port,
                    host="127.0.0.1",
                    proc=process,
                    numRetries=60,
                    waitBetweenRetries=0.1,
                    label=f"smart-parking-{id(self)}",
                )
                with self._lock:
                    self._connection = connection
                    self._process = process
                    self._ready = True
                    self._state = "running"
                    stop = threading.Event()
                    self._worker_stop = stop
                    worker = threading.Thread(
                        target=self._advance,
                        args=(connection, process, stop),
                        name="sumo-stepper",
                        daemon=True,
                    )
                    self._worker = worker
                    worker.start()
            except Exception as error:
                self._stop_owned_process(connection, process)
                with self._lock:
                    self._connection = None
                    self._process = None
                    self._worker = None
                    self._worker_stop = None
                    self._state = "unavailable"
                    self._ready = False
                    self._error = str(error)
            return self.status()

    def pause(self) -> dict[str, Any]:
        with self._operation_lock:
            with self._lock:
                if self._state == "running":
                    self._state = "paused"
            return self.status()

    def resume(self) -> dict[str, Any]:
        with self._operation_lock:
            with self._lock:
                if self._state == "paused":
                    self._state = "running"
            return self.status()

    def reset(self) -> dict[str, Any]:
        with self._operation_lock:
            self._stop_current()
            if self.parking_traffic is not None:
                self.parking_traffic.close()
                self.parking_traffic.completed.clear()
            with self._lock:
                self._snapshot = self._empty_snapshot()
                self._state = "stopped"
            return self.start()

    def _advance(self, connection: Any, process: subprocess.Popen[Any], stop: threading.Event) -> None:
        while not stop.is_set():
            with self._lock:
                state = self._state if self._connection is connection else "stopped"
            if state != "running":
                stop.wait(0.05)
                continue
            try:
                connection.simulationStep()
                vehicle_ids = connection.vehicle.getIDList()
                vehicles = []
                speed_total = 0.0
                for vehicle_id in vehicle_ids:
                    speed = float(connection.vehicle.getSpeed(vehicle_id))
                    speed_total += speed
                    if len(vehicles) < 1200:
                        x, y, elevation = connection.vehicle.getPosition3D(vehicle_id)
                        road_id = connection.vehicle.getRoadID(vehicle_id)
                        vehicles.append({
                            "id": vehicle_id,
                            "x": float(x),
                            "y": float(y),
                            "elevation": float(elevation),
                            "floor": max(1, min(6, round(elevation / self.floor_height) + self.ground_floor)),
                            "road_id": road_id,
                            "in_city": road_id.startswith(("city_", ":C")),
                            "on_ramp": road_id.startswith(("up_", "down_")) or abs(elevation / self.floor_height - round(elevation / self.floor_height)) > .02,
                            "speed_mps": speed,
                            "angle": float(connection.vehicle.getAngle(vehicle_id)),
                        })
                simulation_time = float(connection.simulation.getTime())
                if self.parking_traffic is not None:
                    vehicles = self.parking_traffic.step(connection, vehicles, simulation_time)
                with self._lock:
                    if self._connection is not connection:
                        return
                    self._snapshot = {
                        "simulation_time": simulation_time,
                        "vehicle_count": len(vehicles),
                        "mean_speed_mps": speed_total / len(vehicle_ids) if vehicle_ids else 0.0,
                        "vehicles": vehicles,
                        "parking_vehicles": [{"vehicle_id": vehicle_id, "slot_id": item["slot_id"], "phase": item["phase"], "next_transition_at": item["due"]} for vehicle_id, item in self.parking_traffic.active.items()] if self.parking_traffic else [],
                        "traffic_lights": {tls: connection.trafficlight.getRedYellowGreenState(tls) for tls in connection.trafficlight.getIDList()},
                    }
                stop.wait(self.step_length)
            except Exception as error:
                with self._lock:
                    if self._connection is not connection:
                        return
                    self._state = "error"
                    self._ready = False
                    self._error = f"SUMO simulation stopped: {error}"
                self._stop_owned_process(connection, process)
                with self._lock:
                    if self._connection is connection:
                        self._connection = None
                        self._process = None
                return

    @staticmethod
    def _stop_owned_process(connection: Any | None, process: subprocess.Popen[Any] | None) -> None:
        if connection is not None:
            try:
                connection.close(wait=False)
            except Exception:
                pass
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass

    def _stop_current(self) -> None:
        with self._lock:
            stop = self._worker_stop
            worker = self._worker
            connection = self._connection
            process = self._process
            if stop is not None:
                stop.set()
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=2)
        self._stop_owned_process(connection, process)
        if worker is not None and worker is not threading.current_thread() and worker.is_alive():
            worker.join(timeout=2)
        with self._lock:
            self._worker = None
            self._worker_stop = None
            self._connection = None
            self._process = None

    def stop(self) -> dict[str, Any]:
        with self._operation_lock:
            self._stop_current()
            if self.parking_traffic is not None:
                self.parking_traffic.close()
                self.parking_traffic.completed.clear()
            with self._lock:
                self._snapshot = self._empty_snapshot()
                self._state = "stopped"
                self._error = None
            return self.status()

    def close(self) -> None:
        with self._operation_lock:
            self._stop_current()
            with self._lock:
                if self._state not in {"unavailable", "error"}:
                    self._state = "stopped"
