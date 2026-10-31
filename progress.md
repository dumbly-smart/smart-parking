# Project progress

## Current implementation

- FastAPI and SQLite provide atomic RFID vehicle entry/exit, parking status, event streaming, optimizer benchmarks and prediction endpoints.
- Slot occupancy is derived from active RFID sessions. The controller and server use persistent idempotency keys so retries do not duplicate transactions.
- ESP32 DevKit firmware reads the RC522, displays status on the OLED, drives five slot LEDs, and actuates the supervised tabletop servo only after confirmed authorization.
- The browser dashboard shows the configured parking layout, live slot state, vehicle animations, predictor comparisons, and optimizer comparisons.
- The reproducible synthetic forecasting experiment compares LSTM, GRU, Transformer and persistence on a chronological 70/15/15 split.
- Allocation compares first available, exact enumeration, GA, PSO and ACO using a shared objective and seeded scenarios.
- The camera-independent final A4 report and editable DOCX are generated from repository data and diagrams. Its prose has been revised for clarity and a natural academic voice; the abstract is exactly 250 words.

## Hardware evidence

The recorded controller run includes two RFID scans and two successful API transactions. Entry and exit response latency samples were 1,431 ms and 1,220 ms. The status log showed S1 occupied and then free. Visual LED output, servo travel, supply current, and controlled Wi-Fi recovery remain unverified. These limits are stated in the report and hardware summary.

## Current deliverables

- Final report: `output/final_submission/Smart_Parking_Final_Report.pdf`
- Editable report: `output/final_submission/Smart_Parking_Final_Report.docx`
- Hardware diagrams and pin map: `docs/hardware/`
- Dataset and provenance: `review_outputs/2026-10-15/dataset/`
- Controller measurement procedure: `docs/hardware/measurement_procedure.md`

## Remaining submission work

- Confirm the supplied Google Drive folder is available to the intended reviewers.
- Complete the institution's similarity review; no detector score is represented by this project.
- Fill in institution, course and faculty fields in the report.
- Collect further physical trials for LED visibility, servo travel, power and controlled Wi-Fi recovery.
