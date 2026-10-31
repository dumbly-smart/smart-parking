# Garage-scale SUMO and parking model

## Goal

Replace the city-street map with a local-coordinate basement garage model that keeps the five configured parking slots live, displays the whole parking-level plan as a schematic, and places SUMO vehicles on roads that match the same 3D model.

## Layout reference

Use Haneda Airport P2's published 5F reserved-car floor plan as the full-level reference. The official guide gives the complete numbered parking layout, and the operator lists 396 reserved spaces on 5F within a 2,315-space facility. The app links and attributes the guide. The local-coordinate 3D model is a visual reconstruction and does not claim to be a surveyed/as-built plan.

The current backend configuration remains authoritative for the five monitored spaces. Other parking bays in the full-level view are context only and must not show live availability.

## Interaction and visual design

- The primary view is a dark, elevated 3D model of one garage level, with aisles, ramps, columns, service cores, context bays, and five highlighted configured bays.
- Users can pan and zoom, select a live bay, inspect its state, and reset the view.
- SUMO vehicles use local metre coordinates and move through the modeled garage. They remain a separate simulation layer; they do not overwrite hardware or parking API occupancy.
- The map legend distinguishes the five live spaces, unmonitored plan bays, SUMO traffic, ramps, and service areas.
- Keep the existing parking lifecycle, hardware event stream, slot list, forecasts, and benchmarks.

## Backend design

- A versioned local garage-layout JSON is the shared coordinate source for the map API and SUMO network builder.
- SUMO publishes `x`, `y`, `speed_mps`, and heading in metres/degrees; no geographic conversion or OSM data is involved.
- SUMO start, pause, resume, reset, and shutdown retain owned-process cleanup.
- Missing SUMO keeps the parking dashboard usable and shows an offline simulation state.

## Source and limitation

Reference: [Haneda Airport P2 official 5F floor-map PDF](https://www.aeif.or.jp/haneda/pdf/parking/p2/floor_p2.pdf), page 5. The [operator's P2 page](https://www.aeif.or.jp/haneda/parking/p2/) states that P2 has 2,315 spaces and its 5F reservation area covers 396 spaces. The 3D rendition uses local metre coordinates; only S501–S505 represent the five configured live backend slots.
