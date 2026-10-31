# Multi-floor garage implementation plan

**Goal:** Six architectural decks with connected SUMO elevation-aware traffic, floor inspection, assembled and exploded views, and five live bays on 5F.

**Design:** Preserve the 5F reference and emulate the other decks using its parking template. Each physical floor is 4.2 m above the previous one. Two exterior one-way ramp banks connect adjacent floors. SUMO node/edge coordinates include elevation; TraCI supplies position3D. Exploded rendering changes display separation only, preserving vehicle elevation interpolation. Modeled per-floor capacity is distinct from the operator's reported facility capacity.

**Files and steps:**
- [x] Add multilevel map/network generation and verify route continuity plus six distinct elevations.
- [x] Extend validated map and vehicle contracts and carry position3D through the service.
- [x] Build six detailed decks with instanced markings/columns/parked context cars, ramp surfaces, lighting, floor selection, and assembled/exploded controls.
- [x] Preserve live bay selection, parking events and hardware gates on 5F.
- [x] Run focused contract checks, real SUMO FCD verification, and desktop/mobile browser checks; document limitations.

**Reference:** https://www.aeif.or.jp/haneda/pdf/parking/p2/floor_p2.pdf . Geometry and floor height are emulation parameters, not surveyed dimensions. Context cars and SUMO traffic are simulated; only five backend slots report live occupancy.

**Evidence:** 11 focused contract/dashboard tests pass. A 1,800-second native SUMO run observed 580 vehicles across all six floor elevations, 265,206 fractional ramp-elevation samples, and 28 vehicles at both ground and roof height. Summary: `output/sumo/multilevel-verification.json`. Browser checks cover all-deck exploded and assembled modes, individual 6F, live 5F focus, and mobile layout.
