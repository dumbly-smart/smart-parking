# Smart Parking System — Implementation Design

## Scope
Build a low-cost smart parking prototype with five parking slots using:
- ESP32-CAM for parking-lot video/image capture over Wi-Fi
- ESP32 DevKit as the on-site hardware controller
- RC522 RFID reader and 2–5 RFID tags for vehicle identification
- 5 LEDs for slot indication
- OLED for assignment/status output
- SG90 servo for the entry gate
- Laptop/server for computer vision, prediction, optimization, API, persistence, and dashboard

The implementation must directly support the three project tasks:
1. Replace FCFS parking with GA, PSO, and ACO and compare their results.
2. Predict future occupancy from historical occupancy, weather, holidays, event schedules, and time of day using LSTM, GRU, and a temporal Transformer.
3. Optimize walking distance, congestion, waiting time, and fairness simultaneously.

## Architecture

ESP32-CAM -> Wi-Fi -> Python backend/server -> Wi-Fi -> ESP32 DevKit

The ESP32-CAM streams or snapshots the parking area. The server detects the occupancy state of five fixed slot regions. The backend stores occupancy history and contextual features, runs the prediction models, runs the selected allocation optimizer, and exposes APIs/dashboard state. The ESP32 DevKit receives assignment commands and controls RFID, OLED, LEDs, and the servo gate.

## Runtime Responsibilities

### ESP32-CAM
- Join configured Wi-Fi network.
- Serve MJPEG stream and/or JPEG capture endpoint.
- Expose health/status endpoint.
- No heavy ML inference on-device.

### ESP32 DevKit
- Read RC522 UID.
- Send entry request to backend with UID.
- Receive assigned slot and gate command.
- Display assigned slot on OLED.
- Blink/illuminate the assigned slot LED.
- Open SG90 gate, wait configured interval, close gate.
- Poll or receive updated occupancy/assignment state.
- Recover cleanly from network/backend failure.

### Python Backend
- FastAPI application.
- SQLite persistence.
- Parking-slot state model for five slots.
- Vehicle entry/exit endpoints.
- Camera occupancy update pipeline.
- Prediction service.
- Allocation service.
- Benchmark/comparison endpoints.
- Simple browser dashboard.

## Computer Vision
Use fixed parking-slot Regions of Interest (ROIs) rather than full object detection for the first working version.

For each camera frame:
1. Resize/normalize frame.
2. Crop five configured parking-slot ROIs.
3. Run occupied/free classifier for each crop.
4. Apply confidence threshold and temporal smoothing.
5. Produce occupancy vector such as [1,0,1,0,0].
6. Persist state changes with timestamp.

Two detector modes will exist:
- `heuristic`: image-difference/edge based baseline so the system runs without a trained model.
- `cnn`: small TensorFlow/Keras binary classifier loaded from a saved model.

ROI coordinates will live in configuration so the physical camera position can be calibrated without code changes.

## Prediction
Shared time-series preprocessing will create sequences from:
- recent occupancy ratio/count
- hour of day
- day of week
- weather encoding
- holiday flag
- event flag

Three comparable predictors will be implemented:
- LSTM
- GRU
- compact temporal Transformer

All three will train/evaluate on identical train/validation/test splits.

Metrics:
- MAE
- RMSE
- MSE
- inference latency

The runtime service loads the selected best model if a trained artifact exists. If no model exists yet, it uses a deterministic baseline predictor so the end-to-end system remains runnable.

## Allocation Optimization
Each available slot has normalized objective values:
- walking distance
- congestion
- waiting-time contribution
- fairness penalty

Default weighted cost:
`0.35*distance + 0.30*congestion + 0.20*waiting + 0.15*fairness`

Weights are configurable.

Three optimizers will use the same cost interface:
- Genetic Algorithm
- Particle Swarm Optimization
- Ant Colony Optimization

All algorithms return:
- chosen slot/assignment
- best cost
- iteration count
- execution time
- objective breakdown

A benchmark runner compares GA, PSO, and ACO over the same scenarios.

## API
Initial endpoints:
- `GET /health`
- `GET /api/parking/status`
- `POST /api/vehicle/entry`
- `POST /api/vehicle/exit`
- `POST /api/camera/occupancy`
- `GET /api/prediction`
- `POST /api/allocation/run`
- `GET /api/benchmarks/optimizers`
- `GET /api/benchmarks/predictors`
- `GET /dashboard`

`POST /api/vehicle/entry` returns an assigned slot and gate action.

## Database
SQLite tables:
- `parking_slots`
- `occupancy_events`
- `vehicles`
- `parking_sessions`
- `context_samples`
- `allocations`
- `optimizer_runs`
- `prediction_runs`

Database initialization seeds five slots with configurable walking-distance and zone metadata.

## Dashboard
A lightweight HTML/CSS/JS dashboard served by FastAPI will show:
- five slot cards and live occupancy
- latest RFID/vehicle
- latest assignment
- prediction value/model
- currently selected optimizer
- GA/PSO/ACO comparison table
- LSTM/GRU/Transformer comparison table
- ESP32/ESP32-CAM connectivity indicators

No frontend framework is required for v1.

## Repository Layout

```
smart-parking/
├── README.md
├── .gitignore
├── .env.example
├── pyproject.toml
├── requirements.txt
├── config/
│   ├── parking.yaml
│   └── rois.example.json
├── backend/
│   └── app/
│       ├── main.py
│       ├── config.py
│       ├── db.py
│       ├── models.py
│       ├── schemas.py
│       ├── services/
│       │   ├── allocation.py
│       │   ├── prediction.py
│       │   └── occupancy.py
│       └── static/
├── vision/
│   ├── capture.py
│   ├── detector.py
│   ├── train_classifier.py
│   └── collect_dataset.py
├── prediction/
│   ├── data.py
│   ├── train_lstm.py
│   ├── train_gru.py
│   ├── train_transformer.py
│   └── compare.py
├── optimization/
│   ├── fitness.py
│   ├── ga.py
│   ├── pso.py
│   ├── aco.py
│   └── benchmark.py
├── firmware/
│   ├── esp32_controller/
│   │   └── esp32_controller.ino
│   └── esp32_cam/
│       └── esp32_cam.ino
├── scripts/
│   ├── seed_demo_data.py
│   └── run_demo.py
├── tests/
│   ├── test_fitness.py
│   ├── test_optimizers.py
│   ├── test_api.py
│   ├── test_prediction_data.py
│   └── test_occupancy.py
└── docs/
    └── superpowers/specs/
        └── 2026-09-03-smart-parking-design.md
```

## Error Handling
- ESP32 retries Wi-Fi and backend communication with capped backoff.
- Gate remains closed on malformed/failed allocation response.
- Backend rejects assignment to occupied slots.
- Camera state uses last-known value when one frame fails.
- Vision confidence below threshold does not immediately flip slot state.
- Optimizers receive deterministic seeds in tests.
- Missing ML model artifacts trigger baseline predictor rather than crash.

## Testing
### Python unit tests
- fitness calculation and normalization
- occupied-slot exclusion
- GA/PSO/ACO produce valid available-slot assignments
- optimizer benchmark schema
- time-series sequence building
- prediction fallback behavior
- camera occupancy smoothing
- entry API response and persistence

### Integration tests
- simulated RFID entry -> allocation -> backend response
- simulated camera state update -> database state
- five-slot demo lifecycle

### Firmware verification
- build instructions for Arduino IDE/PlatformIO
- documented pin map
- serial logs for Wi-Fi, RFID, assignment, gate states

## Demo Mode
The repository must run without hardware:
- seed demo occupancy/context data
- simulated camera occupancy
- simulated RFID entry endpoint
- deterministic fallback predictor
- full optimizer comparison

Then hardware can be enabled by changing environment/config values only.

## Pin/Hardware Assumptions
Exact ESP32 DevKit pins will be centralized in firmware constants and documented in README. The RC522 uses SPI. OLED uses I2C. Servo gets 5V supply with common ground to ESP32. LEDs each use their own 220–330 ohm resistor. ESP32-CAM receives its own stable 5V supply.

## Acceptance Criteria
1. System boots in demo mode and dashboard opens.
2. Five slots show free/occupied state.
3. Vehicle entry request returns a valid free slot.
4. GA, PSO, and ACO can each be selected and benchmarked.
5. No optimizer assigns an occupied slot.
6. LSTM, GRU, and Transformer training scripts run against the same prepared dataset.
7. Predictor comparison report is generated.
8. ESP32 controller firmware can send RFID entry request and actuate OLED/LED/servo from returned assignment.
9. ESP32-CAM firmware exposes a usable camera stream/snapshot endpoint.
10. End-to-end hardware flow works over Wi-Fi without a USB tether between the on-site controller and laptop/server.
