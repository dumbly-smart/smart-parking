# Detailed garage models and animation

Upgrade every visible asset class in the existing six-deck SUMO scene. Preserve actual simulation positions/elevations and the five live backend bays.

- Build reusable sedan, SUV and hatchback templates with colored body panels, glazing, interior, trim, wheel assemblies, lamps, handles, mirrors and articulated doors.
- Render distant/parked cars with merged geometry and instancing; use articulated detail near the camera. Animate wheels by traveled distance, front steering by yaw changes, brake lamps by deceleration, indicators during turns, and reverse lamps during reverse parking.
- Add floor colors, layered rails, ceiling beams/ducts/pipes, safety markings, wheel stops, EV chargers/cables, fire equipment, fan housings/blades, security cameras and sliding lift doors.
- Detail ramp barriers, girders, reflective posts and state-driven beacons; improve site furniture, entry booth and entrance gate.
- Provide an inspection camera and day/evening lighting. Decorative mechanical animation is independently toggleable and honors reduced motion. SUMO and live occupancy remain authoritative.
- Verify model structure and animated joints in the browser, check state-dependent animation with deterministic inputs, run existing focused regression checks and capture close-up/overview evidence.

Implemented: three detailed vehicle types (204–207 components), twelve paints, articulated joints and state-based lamps; detailed mechanical/site assets; instanced distance LOD; inspection camera and lighting controls.

Underground extension: B2/B1 at −8.4/−4.2 m, G at 0 m, three upper decks, terrain cutaway with stratified soil and retaining walls. SUMO routes now enter/exit at G and physically traverse the basement ramps. Floor IDs and five live bay IDs remain stable. Ground-floor offset travels with map metadata into the SUMO service.

Verification: 31 browser model/motion checks and 12 focused Python contract/dashboard checks pass. SUMO native 90-second smoke check passes; longer elevation verification is recorded separately under output/sumo.

Native 1,500-second SUMO audit: all six deck IDs and all ten ramps observed, elevations −8.4 to +12.6 m. Browser interaction checks cover cutaway, basement inspection, lighting, mechanics and mobile overflow. Read-only review found a foundation occlusion in exploded mode; earth is now hidden only in exploded view, preserving unobstructed floor inspection.
