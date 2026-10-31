# Natural city and retained detail

User wants visible detail at district distance and a more natural environment with lighting and shadows. Continue autonomously under prior authorization.

- Replace three-box distant cars with reusable multi-part body/glazing, wheel/rim, grille, mirror and lamp templates; preserve instancing and moving-car animations near the camera. Keep detailed medium geometry at all parked-car distances.
- Add a separate environment module for deterministic tiled surfaces, natural terrain outside the street network, clustered varied trees, soft sky/haze/clouds and landscaped park detail. Preserve SUMO road footprints, underground cutaway and all five live sensors.
- Enable broad city shadows by default, use focused shadow coverage for close views, and provide natural daylight/golden-hour/evening lighting. Use shadow proxies for architectural mass to avoid drawing every window into shadow maps.
- Add roof terraces, gardens, service detail and variation that remain legible in overview. Increase render resolution and texture filtering for distant detail.
- Verify retained far geometry, shadow coverage/casters, atmosphere/landscape controls, city/floor visibility, live signal correspondence and mobile layout. Capture before/after city and close views, and run existing focused checks.

Implemented and verified: 12 natural-environment browser checks (including actual shadow-on/off pixel comparison), 33 model/animation checks, 16 city integration/browser checks, and 17 focused Python checks. A focused read-only review found no material issues. Native SUMO geometry/routes are unchanged. Evidence: output/3d/natural-city-verification.json and output/playwright/natural-city-*.png.

Distance detail is retained through full shared static geometry and instancing. High detail supersamples at 1.5–2× CSS resolution; Balanced reduces resolution without reverting models to boxes. Full-detail city views require more GPU work.
