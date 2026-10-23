# Hardware diagrams and pin reference

These are editable Graphviz sources and monochrome exports. The GPIO assignments
are read from `firmware/esp32_controller/include/pins.h`; the camera module
signals are read from `firmware/esp32_cam/include/camera_board.h`. The diagrams
show a proposed bench assembly and are not evidence of physical testing.

- `system_architecture.dot` — system block diagram.
- `wiring_diagram.dot` — detailed component wiring and signal map.
- `circuit_diagram.dot` — electrical connection schematic.
- `pin_connections.csv` — signal-level GPIO table.
- `bill_of_materials.csv` — component and supply list.

Regenerate vector and raster views after editing a DOT source:

```bash
for name in system_architecture wiring_diagram circuit_diagram; do
  dot -Tsvg "docs/hardware/$name.dot" -o "docs/hardware/$name.svg"
  dot -Tpng "docs/hardware/$name.dot" -o "docs/hardware/$name.png"
  rsvg-convert -f pdf --keep-aspect-ratio --page-width 297mm --page-height 210mm \
    "docs/hardware/$name.svg" -o "docs/hardware/$name.pdf"
done
```

`system_block_diagram.png`, `.svg`, and `.pdf` are report-friendly aliases of the system diagram.
Check the source pin assignments against the CSV and diagram safety labels with:

```bash
python scripts/validate_hardware_diagrams.py
```

All diagram exports use black strokes and white backgrounds. They depict the
firmware's configured signals; verify board markings, module variants, voltage
rails, polarity, and supply ratings before bench connection. Keep ESP32 logic
at 3.3 V. Power the SG90 from a separate regulated 5 V supply with common
ground, keep independent 5 V outputs isolated, and use the servo only for a
supervised lightweight tabletop model.
