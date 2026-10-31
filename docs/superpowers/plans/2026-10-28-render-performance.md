# Render performance optimization

Baseline city profile: about 2,114 draw calls, 8.2 million triangles, 7 FPS with shadows, 10 FPS without shadows, and 11 FPS at balanced resolution without shadows. CPU update is about 1 ms; renderer submission is 14–28 ms. Native traffic and parking logic remain unchanged.

1. Combine static vehicle materials into paint, glazing and vertex-colored accessories, retaining every triangle and lamp emission. Consolidate parked cars per floor rather than repeating material batches in six spatial chunks. Keep full articulated close-up vehicles.
2. Replace logarithmic depth with camera-relative near-plane precision so normal early depth rejection can work. Cache/static-throttle city shadow updates while keeping close-up traffic shadows responsive.
3. Add Auto render resolution with stable sampling/hysteresis. Preserve manual High detail and Balanced modes and all model geometry. Stop rendering when scene is offscreen; keep authoritative simulation state updates.
4. Remove allocations and unused hidden-car joint updates from the animation hot path; measure before/after with the same paused simulation and camera. Verify appearance, all five live bays, shadows, signal states, full geometry, model joints, floor/city controls and mobile rendering.

Implemented: indexed full geometry, three material batches per static model, whole-floor batching, conservative solid-slab occlusion, deferred near rigs, active-only instance buffer uploads, camera-relative depth precision, proxy/cached shadows, Auto resolution with hysteresis and offscreen rendering pause. All 204–207 model components remain available.

Measured with a frozen 100-vehicle SUMO snapshot at a 776×650 canvas: Auto 29 FPS, High 17 FPS; 785 draw submissions and 5.26M triangles. Baseline overview was about 7 FPS, 2,114 submissions and 8.16M triangles with99vehicles. Hardware/browser-dependent measurements; results are not a universal FPS guarantee. Evidence output/3d/render-performance.json.

Review fix: cached shadows were not invalidated after removal or reduced-motion occupancy changes. verify_shadow_cache.js reproduced an arrival invalidation failure before the fix and passes all three scenarios afterward. Membership changes, immediate repositioning and parking completion now mark shadows dirty.

Final verification: 10 optimization browser checks, 41 vehicle/motion checks, 16 city integration checks, 12 natural-environment checks, 3 shadow-cache regression scenarios, 6 deterministic render-budget checks and 17 focused Python tests pass. Tests verify on/offscreen pausing and resumption, floor inspection restoration, unchanged triangle counts and accessory color/emission, lazy wheel creation with continuous roll, and fixed shadow invalidation.

Final default Auto uses a 2048 shadow map and distance-aware cached shadow updates; High remains 4096. Low-cost vegetation shadow masses replace repeated leaf-cluster shadow submissions while keeping visible foliage geometry. Test-browser profile with 100 frozen native vehicle positions: Auto29FPS, High17FPS, 785 draw calls, 5.26M triangles; original99vehicle overview7FPS,2114calls,8.16Mtriangles.
