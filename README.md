# Smart Parking

Smart parking prototype with a FastAPI/SQLite server and a fully
hardware-independent demo path. The committed configuration models the current
five-slot rig, while the backend supports any non-empty configured slot set.
The remaining prediction, dashboard, and firmware milestones are tracked in
`progress.md`.

## Backend foundation

Python 3.11 or newer is required. Create an isolated environment and install
the project:

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Run verification and start the development server:

```bash
make test
make lint
make run
```

Open `http://127.0.0.1:8000/health`. The first startup creates the local SQLite
database and idempotently seeds every slot from `config/parking.yaml`.

Open `http://127.0.0.1:8000/dashboard` for the framework-free operations
dashboard. It reads parking status and polls optimizer-benchmark,
predictor-benchmark, and prediction APIs; slot cards are rendered from the
configured status response, so deployments are not limited to the five-slot
demo. Each slot's world position, heading, entry route, and exit route are keyed
by slot ID in `config/parking.yaml`. The scene loads the GLB lot only when the
configured asset slot IDs match the active slots; other layouts use generated
geometry at their configured coordinates. The scene shows live occupancy.
Drag to rotate it, scroll to zoom, or select a space in the model or
list. Enter an RFID value and use **Simulate entry** to allocate a space and
watch the vehicle drive into the returned slot. Select an occupied space (or
enter its RFID) and use **Simulate exit** to watch it leave. The page also shows
selected optimizer/predictor settings, live occupancy, comparison tables,
forecast target time, and stable prediction fallback state.
The dashboard consumes `/api/parking/events/stream` and replays durable SQLite
events in order. Entry assignment and exit events are stored in the same
transaction as their parking changes. The ESP32 reports RFID reads and gate
open/close commands through `/api/parking/hardware-events`, retrying unacknowledged
reports from nonvolatile storage. The scene starts controller car motion when
the gate-open report arrives and moves the gate graphic from gate reports.
Parking status refreshes every 1.5 seconds for server-state reconciliation; insight panels refresh every 10 seconds. Gate reports reflect
servo commands, since the controller has no physical position sensor.

## Physical hardware integration

The controller targets the ESP32 DevKit and drives the RC522, SSD1306, five
slot LEDs, and a supervised tabletop SG90. Slot occupancy follows confirmed
RFID session entry and exit. Firmware source, private LAN setup, API behavior,
power constraints, and the remaining physical checks are documented in
[`docs/hardware/firmware.md`](docs/hardware/firmware.md). The proposed pin map,
editable black-and-white circuit and wiring diagrams, A4 PDF exports, and BOM
are in [`docs/hardware/`](docs/hardware/diagrams.md).

Hardware serial and operator observations can be captured and summarized using
[`docs/hardware/measurement_procedure.md`](docs/hardware/measurement_procedure.md).
For example, capture controller metrics with:

```bash
python -m pip install -e '.[hardware]'
python -m scripts.hardware_evaluation capture \
  --port /dev/ttyUSB0 --output output/hardware/controller.jsonl
```

These logs contain no RFID UID, image, or credential values. A local config and
a backend address reachable on a trusted LAN are required. The optional
bearer-token check protects `/api/*` on the configured hardware service; traffic
is plain HTTP, so keep it on a private network. Firmware compilation
does not establish that a board was flashed or that the wiring is physically
working.

The editable model source is `scripts/build_parking_assets.mjs`. To rebuild
`backend/app/static/models/parking-lot.glb` and `sedan.glb`, run `npm install`
then `npm run build:assets`. The exported GLB files are served with the app;
Node is only needed to regenerate them.

Copy `.env.example` to `.env` to override local configuration. Hardware mode
requires both `SMART_PARKING_MODE=hardware` and
`SMART_PARKING_HARDWARE_ENABLED=true`, preventing accidental physical-mode
startup. Local databases, secrets, datasets, and generated
model artifacts are ignored by Git.

## Allocation comparison

`POST /api/allocation/run` accepts one or more normalized slot candidates and an
`algorithm` value of `ga`, `pso`, `aco`, or `all`. Every algorithm excludes
occupied candidates and uses the same configurable weighted objective. Runs
are persisted and available from `GET /api/benchmarks/optimizers`; supply a
fixed `seed` to reproduce the semantic result.

## Parking lifecycle API

Entry and exit use persistent idempotency keys, so RFID controllers may safely
retry requests after a timeout or lost response. Keys are unique across both
operation types.

```bash
curl -X POST http://127.0.0.1:8000/api/vehicle/entry \
  -H 'Content-Type: application/json' \
  -d '{"rfid_uid":"04-A1-B2-C3","idempotency_key":"entry-0001"}'

curl http://127.0.0.1:8000/api/parking/status

curl -X POST http://127.0.0.1:8000/api/vehicle/exit \
  -H 'Content-Type: application/json' \
  -d '{"rfid_uid":"04-A1-B2-C3","idempotency_key":"exit-0001"}'
```

Representative entry response:

```json
{
  "session_id": 1,
  "rfid_uid": "04-A1-B2-C3",
  "slot_id": 1,
  "slot_name": "S1",
  "optimizer": "ga",
  "allocation_cost": 0.07,
  "entered_at": "2026-09-04T10:00:00.000Z",
  "gate_action": "open"
}
```

Representative status response (the real response contains every configured
slot in configuration order):

```json
{
  "slots": [
    {
      "id": 1,
      "name": "S1",
      "walking_distance": 0.2,
      "zone": "north",
      "occupied": true,
      "updated_at": "2026-09-04T10:00:00.000Z",
      "active_session_id": 1,
      "rfid_uid": "04-A1-B2-C3"
    }
  ]
}
```

Representative exit response:

```json
{
  "session_id": 1,
  "rfid_uid": "04-A1-B2-C3",
  "slot_id": 1,
  "slot_name": "S1",
  "exited_at": "2026-09-04T11:00:00.000Z",
  "gate_action": "open"
}
```

A successful entry assigns only a currently free slot and returns
`gate_action: "open"` after the session, allocation, optimizer result, and slot
state commit atomically. Exit closes that session and releases the same slot.
Expected lifecycle conflicts return HTTP 409 with a stable `detail.code`,
including `no_available_slot`, `vehicle_already_parked`,
`vehicle_not_parked`, and `idempotency_conflict`.

## Prediction preprocessing

Prediction preprocessing reads persisted context, lifecycle, allocation, and
optimizer records into regular five-minute buckets. Every future predictor
uses the same chronological 70/15/15 split: twelve historical buckets (one
hour) predict the next bucket's normalized occupancy.

Features include occupancy trends, cyclic time, weather, holiday/event state,
entry/exit activity, active sessions, returning-vehicle rate, and aggregate
walking-distance, congestion, and fairness values. RFID identifiers remain in
the lifecycle boundary and are never included in model arrays. Continuous
features are standardized from training data only, preventing validation/test
leakage. Runtime inference uses the same aggregation and immutable fitted
scaler, is cached per five-minute target bucket, and never trains inside an API
request.

## Prediction demo data and model comparison

Seed fourteen days of deterministic five-minute history into an initialized,
dedicated SQLite database (the generator rejects unrelated active parking
state):

```bash
.venv/bin/python -m scripts.seed_prediction_demo_data \
  --database-url sqlite:///./data/prediction-demo.db \
  --dataset-key prediction-demo \
  --seed 20260908 \
  --days 14
```

Rerunning the command replaces only rows owned by that dataset key. Unrelated
parking records are preserved, and generated RFID identifiers remain inside
the lifecycle database boundary.

Install the optional ML dependency and train all three model families:

```bash
pip install -e '.[ml]'
.venv/bin/python -m scripts.train_prediction_models \
  --database-url sqlite:///./data/parking.db \
  --artifact-directory artifacts/prediction
```

The database snapshot is prepared exactly once. LSTM, GRU, and temporal
Transformer trainers receive the same immutable `PreparedDataset` and
`split_id`; they cannot perform private preprocessing or splitting. Every run
uses shared fitting rules and reports MAE, MSE, RMSE, and median per-example
inference latency on the untouched test split.

Each model is saved as a content-addressed `.keras` file. Its atomically
published JSON manifest records the artifact digest, data contract,
hyperparameters, split sizes, framework versions, metrics, and fitted
non-RFID scaler contract. The training command validates and atomically stores
the completed comparison in SQLite.

`GET /api/benchmarks/predictors` returns persisted LSTM/GRU/Transformer
metrics. `GET /api/prediction` predicts the next aligned five-minute bucket.
Set `SMART_PARKING_SELECTED_PREDICTOR` to `baseline`, `lstm`, `gru`, or
`transformer`, and set `SMART_PARKING_PREDICTION_ARTIFACT_DIRECTORY` when
artifacts live elsewhere. Before loading an artifact, runtime validates its
manifest schema, split ID, feature order, fixed geometry, scaler, basename,
and SHA-256. Missing or incompatible artifacts use the deterministic latest
occupancy baseline and report only a stable non-sensitive fallback reason.

GRU is the recommended affordable deployment candidate because it has fewer
gates than LSTM and far less attention overhead than the Transformer for this
short twelve-step history. Final selection should still use the measured
quality and latency report produced on the target machine.

## Academic review experiments

Generate the dated simulated dataset, train and compare the three neural
models against persistence, run NSGA-II/GA/PSO/ACO benchmarks against first-available
and exhaustive-search references, and assemble the report:

```bash
python -m pip install -e '.[dev,ml]'
make review
```

The workflow uses a dedicated SQLite database under
`review_outputs/2026-10-15/dataset/`, stores review CSV/JSON/PNG outputs and a
shareable ZIP under the same dated directory, and leaves model binaries in the
ignored `artifacts/prediction/`. `review_outputs/2026-10-15/REPRODUCE.md`
documents each individual Make target. These observations are simulated and
the reported inference timings are server measurements, not microcontroller
benchmarks.

## Simulated end-to-end demo

Seed deterministic history, start the API, then run the demo client in a second
terminal:

```bash
.venv/bin/python -m scripts.seed_prediction_demo_data \
  --database-url sqlite:///./data/parking.db \
  --dataset-key dashboard-demo \
  --seed 20260912 \
  --days 14

make run

.venv/bin/python -m scripts.run_simulated_demo \
  --base-url http://127.0.0.1:8000 \
  --rfid-uid DEMO-CARD-001 \
  --idempotency-key dashboard-demo-entry-001
```

The client creates one simulated RFID lifecycle entry, runs the optimizer
comparison, reads the prediction, and prints a privacy-safe JSON summary. Its
output omits the RFID value; refresh `/dashboard` to observe the resulting
slot state and comparison data.

## Five-space garage and SUMO traffic model

The dashboard models six parking decks with slabs, columns, railings, elevator
lobbies, contextual parked cars and ten exterior ramps. Choose B2, B1, G, 1F, 2F or the 3F roof to inspect
a deck, use **Exploded** to separate the decks for inspection, or **Assembled**
to see the physical floor spacing. **Live bays · 2F** focuses the five tracked
spaces. Their existing allocation and hardware workflows still drive their
occupancy and entry/exit animations.

The reference is Haneda Airport P2's published floor guide. The operator lists 2,315
spaces across P2 and designates all 396 spaces on 5F for reservation. Its
[published floor-map PDF](https://www.aeif.or.jp/haneda/pdf/parking/p2/floor_p2.pdf)
contains the complete six-level guide; page 5 shows 5F zones, stall numbering,
elevators, and up/down circulation. The app uses S501–S505 for its five live
spaces. All six decks use an emulated version of the reconstructed 396-bay 5F
template (2,376 modeled bays); these modeled counts are distinct from the
operator's actual facility count. Floor height is an emulation parameter of
4.2 metres. Two decks are underground at −8.4 m and −4.2 m; G is street level. This basement arrangement is a design emulation, not a claim about the source facility. The model is not a surveyed/as-built reconstruction of every floor.

Vehicles have three distinct bodies (sedan, SUV, hatchback), twelve paint colors,
and 204–207 geometric components including interiors, mirrors, trim, lamps,
wheels and articulated doors. **Inspect car** follows a SUMO vehicle. Wheel roll,
front steering, turn indicators and brake lights follow vehicle motion; live-bay
parking includes a stopped gear change, reverse arc and reversing lights. Gates
open on approach. Ceiling ducts, sprinklers, EV equipment, fan rotors, cameras,
lift doors, ramp beacons and roof solar canopies add detail. Mechanical previews
can be paused independently; lighting offers daylight/evening and optional shadows.
Spatial levels of detail and instancing preserve close-up detail at garage scale.

**Underground cutaway** reveals the basement decks, exposed soil strata and
retaining walls. Turning it off hides basement geometry and traffic in the
whole-building view; selecting B2 or B1 still allows floor inspection. Internal
floor IDs stay 1–6 and the five live bay IDs stay unchanged; displayed 2F maps to
internal deck 5. Renderer and SUMO use the same physical elevations.

The garage is surrounded by **Parkflow Central**, a fictional city district about
1.2 km across: 101 buildings, a mall, apartments, offices, hotels, shops, a fountain
park, sidewalks, trees, shelters, street lamps and detailed roof equipment. The
city uses locally generated geometry with instancing; no third-party model
service or external asset download is required. **City view** fits the district;
click the P2 marker or **Building view** to return to the garage. Shift-drag or
right-drag pans the camera; scroll zooms. **City scenery** hides the district.
Selecting a garage floor hides city buildings and street vehicles for inspection.

The SUMO network includes 124 directed city/access roads and 16 signalized
intersections. Arrival and departure routes connect the streets to every garage
level; through traffic also crosses the district. Rendering uses lane shapes and
junction polygons exported from the compiled SUMO network. The 64 signal heads
use native controlled-link indices and TraCI signal states. Park pedestrians and
fountain jets are decorative mechanical previews, independently pauseable with
**Mechanical animations**. They do not affect the five live parking sensors.
Evening mode illuminates windows and street fixtures. Camera-relative near-plane precision keeps facade layers stable across street
and district views while allowing normal early depth rejection.

The natural-environment upgrade keeps all 204–207 vehicle components in distant
static batches, including parked cars; the city overview no longer replaces cars
with three boxes. **Auto (smooth)** is the default: it adapts render resolution between 0.75×
and the device-appropriate ceiling using frame-time sampling and hysteresis.
**High detail** renders at 1.5–2× CSS resolution; **Balanced** uses a fixed lower
resolution. All modes preserve the same model geometry.

City surfaces use deterministic world-space asphalt, paving, plaster, grass and
wood textures with mipmaps and anisotropic filtering. Reflective glass, planted
courtyards, clustered trees, rooftop gardens, solar arrays, pergolas, a curved
park walk and a pond add variation. Continuous rolling terrain and atmospheric
sky/clouds surround the district. Terrain stays flat under the SUMO streets and
has an actual opening for the underground garage cutaway.

**Soft shadows** is enabled by default. A shadow map up to 4096 pixels covers
the city and focuses more tightly when the camera approaches street level.
Instanced building masses cast shadows without redrawing every window frame.
Lighting offers **Daylight**, **Golden hour** and **Evening**; up to four nearby
street lights illuminate street-level evening views. Mechanical previews also
control foliage breeze and cloud movement.

Static vehicles consolidate their materials into paint, glass and vertex-colored
accessories while preserving every triangle, original color and lamp emission.
Indexed geometry avoids processing duplicate vertices. Parked cars batch across
a whole floor, and conservative slab occlusion skips only cars completely hidden
behind concrete. Selecting a floor restores all of its cars. Articulated traffic
rigs are built when approached; simulation motion and wheel roll remain continuous.

City shadows use building/tree masses and cached updates; close views refresh
more frequently. Vehicle creation, removal, reduced-motion changes and completed
parking animations invalidate the cache. GPU rendering pauses when the scene is
offscreen, while simulation state continues to update. Performance measurements
and verification are recorded in `output/3d/render-performance.json`.

Network integration follows the official [SUMO PlainXML documentation](https://sumo.dlr.de/docs/Networks/PlainXML.html)
and [TraCI traffic-light API](https://sumo.dlr.de/pydoc/traci/_trafficlight.html).
The renderer follows [Three.js camera guidance](https://threejs.org/manual/pages/cameras.html)
for depth precision at large scale.

SUMO is optional so the parking API remains available without its runtime.
Install the optional SUMO runtime and TraCI integration into the project
environment:

```bash
pip install -e '.[sumo]'
```

Regenerating the optimizer benchmark also requires this SUMO runtime. The
benchmark captures actual allocation requests at parking admissions during an
executed SUMO/TraCI run, then replays each optimizer against the same captured
state. This is measured simulator output, not a live mall feed or a physical
facility trial. Raw candidate snapshots and run provenance are saved with the
benchmark evidence.

Build the local-coordinate garage map and repeatable SUMO traffic routes:

```bash
python scripts/build_haneda_p2_garage.py
```

The script writes the SUMO network under `data/sumo/haneda-p2/` and refreshes
the garage layout asset at `backend/app/static/data/haneda-p2-5f-layout.json`.
SUMO routes enter G at zero elevation, ascend or descend to each deck, circulate, and return to street exit. Network nodes and ramp shapes contain true elevation;
the backend reads TraCI `getPosition3D` and sends `elevation`, `floor`, `road_id`,
and `on_ramp` with every vehicle. Exploded view interpolates the same elevations
using a larger display spacing. Initial departure flows model vehicles already
inside the building, while arrival flows enter at ground level. Neither moving
traffic nor contextual parked cars determine the five live sensor states.
SUMO vehicles use the same metre-based
coordinates as the 3D model and circulate through its entrance, main aisle,
ramps, and return aisle. Start the app as usual; from the dashboard, select
**Start traffic** to launch SUMO, or use pause, resume, and reset controls. To
use another SUMO installation, set `SUMO_HOME` or
`SMART_PARKING_SUMO_BINARY` and `SMART_PARKING_SUMO_CONFIG_PATH` in `.env`.

SUMO traffic is a local garage scenario, not a live vehicle feed. Simulated
vehicle motion stays separate from live slot occupancy, which remains
authoritative in the existing parking API and hardware event stream.
