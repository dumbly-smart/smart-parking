# Hardware measurement procedure

This workflow records measurements only when the corresponding hardware is
connected. It never fills missing values with simulated results. An empty metric
is exported as `NOT TESTED`.

## Setup and capture

1. Wire the controller and camera using `pin_connections.csv` and the diagrams.
   Inspect polarity, 3.3 V logic compatibility, current limits, and common ground
   before applying power. Supply the SG90 and camera from separately regulated
   supplies; never power a servo from an ESP32 GPIO or 3.3 V output.
2. Configure ignored local Wi-Fi files as described in `firmware.md`. Run the
   backend on a trusted, isolated LAN and configure its LAN address in the
   controller. The local hardware API requires bearer authentication for `/api/*`, but uses
   plain HTTP. Keep it on a trusted private network.
3. Build and flash the controller and camera. Confirm the RC522 `VersionReg`
   diagnostic is neither `0x00` nor `0xFF`; those values indicate SPI wiring or
   power trouble. Capture controller serial output
   (JSON event lines plus ordinary status text) with:

   ```bash
   python -m scripts.hardware_evaluation capture \
     --port /dev/ttyUSB0 --baud 115200 --output output/hardware/controller.jsonl
   ```

   Use the camera's serial port as a second capture process and a different
   output file. Stop each process with Ctrl-C. The recorder ignores non-JSON
   status lines and timestamps accepted events on the host.
   Run the Python camera poller with
   `--metrics-jsonl output/hardware/camera-processing.jsonl` to save backend
   detector processing timings returned in response headers. This value covers
   heuristic processing and state reconciliation on the backend, not network
   transfer or OV2640 capture time.
4. For each trial, record operator observations as JSONL using the same schema.
   Add one `rfid_trial` event per attempted card read with a boolean `success`;
   this denominator is needed to calculate RFID read success rate. Add
   `led_observation` events with expected and observed booleans for each slot.
   Add `current_ma` only when measured using a suitable inline meter. Do not
   infer these values from firmware commands or simulation.
5. Export summaries:

   ```bash
   python -m scripts.hardware_evaluation summarize \
     --input output/hardware/controller.jsonl \
     --output-directory output/hardware/controller-summary
   ```

   This writes timestamped source events to CSV and a JSON summary with count,
   mean, median, sample standard deviation and p95 for numeric measurements.
   The JSON identifies its provenance. Empty measurements retain the status
   `NOT TESTED`.

## Repeatable trials

- **RFID:** perform at least 30 deliberate taps across the intended card set;
  mark one trial for each tap and count a success only when the card is
  recognized and the status flow begins. Remove each card before retrying.
- **Entry/exit and API:** run at least 20 valid entries and exits with known
  test cards. Record the event response latency, HTTP status, and expected
  result. Also exercise already-parked, unknown-card, and full-capacity cases;
  rejected operations must leave the gate closed.
- **Duplicate/recovery:** hold a card on the reader, interrupt Wi-Fi during an
  operation, and restart the controller while a request is pending. Confirm
  the idempotency key is reused and no operation causes a second gate command.
- **LEDs:** for each of the five server slot states, record expected and
  observed LED state after the status refresh. When connectivity is lost,
  verify the unknown-state blink behavior.
- **Wi-Fi:** repeat at least 10 disconnect/reconnect trials. Recovery duration
  in the summary is measured from host receipt of the serial disconnect event
  to host receipt of the connected event; serial and host buffering contribute
  measurement error.
- **Gate:** use a supervised tabletop model only. The recorded delay is from
  RFID detection to the servo command, not measured mechanical travel time.
  Physical angle/travel timing requires an external sensor or video analysis.
- **Camera:** collect at least 30 captures at the configured scene and lighting.
  Calibrate all five ROIs against a fixed camera view. Compare each slot output
  with manually labeled frames and report detector failures and uncertain
  observations. Processing time is Python backend time, while camera capture
  time is firmware frame-acquisition time.
- **Memory and power:** firmware free heap is reported at captured events.
  Power consumption is `NOT TESTED` until measured with a suitable current
  meter; USB input current alone may not represent the servo/camera supply.

Keep each trial's date, operator, firmware revision, board identity, power
source, network conditions, and scene configuration with the exported files.
These exports are hardware evidence only when they originate from the physical
serial capture and recorded operator observations. Software tests and synthetic
experiments belong in their separate result directories.
