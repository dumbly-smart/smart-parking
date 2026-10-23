"""Check hardware pin documentation against firmware pin definitions.

Run from the repository root with `python scripts/validate_hardware_diagrams.py`.
This checks source-to-table consistency and presence of critical circuit safety
notes; it does not establish that the proposed wiring has been physically tested.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTROLLER_HEADER = ROOT / "firmware/esp32_controller/include/pins.h"
CAMERA_HEADER = ROOT / "firmware/esp32_cam/include/camera_board.h"
PIN_TABLE = ROOT / "docs/hardware/pin_connections.csv"
DIAGRAMS = (
    ROOT / "docs/hardware/system_architecture.dot",
    ROOT / "docs/hardware/wiring_diagram.dot",
    ROOT / "docs/hardware/circuit_diagram.dot",
)


def constant(source: str, name: str) -> int:
    match = re.search(rf"\b{name}\s*=\s*(-?\d+)\s*;", source)
    if not match:
        raise ValueError(f"Firmware pin constant {name} was not found")
    return int(match.group(1))


def array(source: str, name: str) -> list[int]:
    match = re.search(rf"\b{name}\s*\[\]\s*=\s*\{{([^}}]+)}}", source)
    if not match:
        raise ValueError(f"Firmware pin array {name} was not found")
    return [int(value.strip()) for value in match.group(1).split(",")]


def main() -> int:
    controller = CONTROLLER_HEADER.read_text(encoding="utf-8")
    camera = CAMERA_HEADER.read_text(encoding="utf-8")
    with PIN_TABLE.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))

    expected = {
        ("ESP32 DevKit (firmware target)", "RC522", "SCK"): constant(controller, "RfidSck"),
        ("ESP32 DevKit (firmware target)", "RC522", "MISO"): constant(controller, "RfidMiso"),
        ("ESP32 DevKit (firmware target)", "RC522", "MOSI"): constant(controller, "RfidMosi"),
        ("ESP32 DevKit (firmware target)", "RC522", "SDA/SS"): constant(controller, "RfidSs"),
        ("ESP32 DevKit (firmware target)", "RC522", "RST"): constant(controller, "RfidReset"),
        ("ESP32 DevKit (firmware target)", "SSD1306 OLED", "SDA"): constant(controller, "I2cSda"),
        ("ESP32 DevKit (firmware target)", "SSD1306 OLED", "SCL"): constant(controller, "I2cScl"),
        ("ESP32 DevKit (firmware target)", "SG90 tabletop gate", "Signal"): constant(
            controller, "GateServo"
        ),
    }
    expected.update({
        ("ESP32 DevKit (firmware target)", f"Slot LED {index}", "Anode via 330 ohm resistor"): gpio
        for index, gpio in enumerate(array(controller, "SlotLeds"), 1)
    })

    cam_expected = {
        "PWDN": constant(camera, "Pwdn"), "RESET": constant(camera, "Reset"),
        "XCLK": constant(camera, "Xclk"), "SIOD": constant(camera, "Siod"),
        "SIOC": constant(camera, "Sioc"), "VSYNC": constant(camera, "Vsync"),
        "HREF": constant(camera, "Href"), "PCLK": constant(camera, "Pclk"),
    }
    for pin_name in ("Y2", "Y3", "Y4", "Y5", "Y6", "Y7", "Y8", "Y9"):
        cam_expected[pin_name] = constant(camera, pin_name)
    expected.update({
        ("AI-Thinker ESP32-CAM", "OV2640", signal): gpio
        for signal, gpio in cam_expected.items()
    })

    actual = {
        (row["Board"], row["Component"], row["Signal"]): int(row["GPIO"])
        for row in rows if row["GPIO"] not in ("", "-")
    }
    errors: list[str] = []
    for key, gpio in expected.items():
        if actual.get(key) != gpio:
            errors.append(f"pin table {key}: expected GPIO {gpio}, got {actual.get(key)}")

    diagram_text = "\n".join(path.read_text(encoding="utf-8") for path in DIAGRAMS)
    for token in ("GPIO14", "GPIO25", "GPIO26", "GPIO27", "GPIO32", "GPIO33",
                  "330", "common", "3V3", "5V", "separate", "vehicle barrier"):
        if token.lower() not in diagram_text.lower():
            errors.append(f"diagrams do not document required wiring/safety detail: {token}")
    if "OV2640" not in diagram_text or "AI-Thinker" not in diagram_text:
        errors.append("system/wiring diagrams must identify the AI-Thinker ESP32-CAM and OV2640")
    if "SCK18" not in diagram_text or "MISO19" not in diagram_text or "MOSI23" not in diagram_text:
        errors.append("wiring diagram must label the RC522 SPI pin mapping")
    if errors:
        print("Hardware diagram validation FAILED:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(
        f"Hardware diagram validation passed: {len(expected)} firmware pin mappings match "
        f"{PIN_TABLE.relative_to(ROOT)}."
    )
    print(
        "Electrical and diagram checks passed; this does not verify physical wiring or operation."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
