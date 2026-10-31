# City District Implementation Plan

**Goal:** Surround the detailed garage with a navigable 3D city and connected native SUMO traffic.

**Architecture:** A deterministic district generator supplies one coordinate system for buildings, streets, intersections and garage access. The SUMO builder exports compiled lane shapes and signal link indices to the map asset; a separate Three.js city module batches static detail and animates signal lamps from TraCI. The garage and five live bays retain their IDs and underground geometry.

**Tech stack:** Python, SUMO/netconvert/TraCI, Three.js, existing local model assets.

**Design:** Fictional district about 1.2 km wide; a two-way street grid surrounds a central garage block. Varied towers, apartments, shops, a mall, park, plazas, sidewalks, trees, lamps, bus shelters and roof equipment create depth. City view is the initial camera; Building view, floor inspection and Inspect car remain available. No external art dependencies or claims of geographic accuracy.

- [x] Generate district metadata, connected SUMO streets/garage routes and compiled lane/signal data. Test route continuity, non-overlapping building footprints and surface elevations.
- [x] Build reusable, batched city geometry with detailed facades, street furniture and a park; integrate city visibility/camera, lighting and live traffic signals.
- [x] Verify SUMO traffic crosses city/garage boundaries, signal changes match TraCI, floor inspection remains isolated, browser controls/mobile work, and capture visual evidence.

Review focus: garage access at street elevation; traffic-light lane indices; fictional-building footprints outside streets; city vehicles excluded from garage floor counts; underground cutaway visibility; city camera and floor camera transitions.

Verification: 17 focused Python tests, 16 city browser checks and 31 garage model/animation checks. Native SUMO audit spans 1,800 simulation seconds: 1,478 city vehicle IDs, 177 city/garage transfers, all six decks, all ten ramps, and changing states on all 16 signal controllers. Evidence: output/sumo/city-verification.json, output/3d/city-scene-verification.json and output/playwright/city-district-*.png.

Review correction: central landscaping overlapped native road lanes. Reproduced with test_central_landscaping_never_covers_native_sumo_lanes (RED), moved plaza rectangles into shared district metadata with street setbacks (GREEN). No other material review findings.
