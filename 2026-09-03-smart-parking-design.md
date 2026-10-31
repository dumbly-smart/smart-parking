# Smart Parking System — Current Design

## Objective

Build a demonstrable five-space parking prototype that records RFID-based vehicle entry and exit, assigns only free spaces, shows current state on a dashboard and controller, and compares prediction and allocation methods using reproducible software experiments.

## System components

- ESP32 DevKit controller with RC522 RFID reader, SSD1306 OLED, five slot LEDs and a supervised tabletop servo.
- Local FastAPI service and SQLite database.
- Browser dashboard with a 3D parking layout, vehicle animations, prediction comparisons and optimizer comparisons.
- Server-side LSTM, GRU and temporal Transformer forecasting experiments.
- First-available, exact-enumeration, GA, PSO and ACO allocation comparisons.

## Occupancy and lifecycle

A parking space is occupied while a confirmed RFID vehicle session is active. Entry validates the tag, selects a free space, and commits the session and allocation atomically. Exit closes that same session and releases its space. The controller retries with an idempotency key and never actuates the demo gate without a confirmed response. The dashboard and LEDs display the server's committed status.

## Evaluation

Synthetic forecasts use a chronological 70/15/15 split, twelve historical steps, twenty-seven input features, training-only normalization, a persistence baseline, and regression metrics. Allocation policies share candidate sets, objective terms and deterministic seeds. Hardware logs are timestamped, and only recorded readings are described as measurements.

## Electrical limits

The RC522 and OLED use compatible 3.3 V logic. Every indicator LED has a series resistor. The tabletop servo has a separately regulated supply and a common ground with the controller. The servo model is for supervised tabletop demonstration only.
