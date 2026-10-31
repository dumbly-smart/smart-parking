# Hardware diagrams

The diagrams show the controller assembly used by the project. GPIO labels are taken from `firmware/esp32_controller/include/pins.h` and checked by `scripts/validate_hardware_diagrams.py`. They document intended electrical connections; they do not prove every physical connection in the photographed rig.

- `system_architecture.dot` — controller, local API, database, forecasting, allocation and dashboard flow.
- `wiring_diagram.dot` — signal and power connections.
- `circuit_diagram.dot` — component-level connection schematic.
- `pin_connections.csv` — editable connection list.
- `bill_of_materials.csv` — required components.

Render SVG files with Graphviz: `dot -Tsvg docs/hardware/system_architecture.dot -o docs/hardware/system_architecture.svg` (repeat for the other two diagrams).
