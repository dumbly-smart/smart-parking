# Garage-scale SUMO implementation plan

**Goal:** Model the existing five-slot parking system inside a full garage-level schematic, and run SUMO traffic on matching local-coordinate lanes.

**Reference:** Haneda Airport P2 5F reserved-car floor. The official floor-map PDF shows the complete 396-space level; the operator lists 2,315 spaces for P2 overall. The five configured live slots map to S501–S505. The local-coordinate 3D reconstruction remains explicitly attributed and is not a surveyed/as-built plan.

**Architecture:** A tracked local-coordinate layout JSON feeds the map API, Three.js scene, and SUMO network builder. SUMO vehicle snapshots use the same metre coordinates and animate on the garage aisles. Existing parking occupancy remains sourced from the parking API and hardware stream.

## Tasks

1. Replace the OSM GeoJSON response model with validated garage-layout data: outline, aisles, access ramps, service cores, dimensions, and context bays.
2. Generate a deterministic SUMO network and demand route from that layout. Keep explicit subprocess ownership and return local `x/y` vehicle coordinates.
3. Restore the existing five-slot 3D parking scene, extend it to render the full schematic level, and add SUMO traffic meshes that update in place.
4. Retune dashboard labels and layout around the garage model, with a legend, reference/source link, five-slot status, and simulation controls.
5. Remove the unused city-map assets/generator, update README and environment defaults, then run syntax and live-browser/API smoke checks.
