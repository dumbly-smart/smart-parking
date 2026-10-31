# Hardware measurement procedure

Use timestamped JSONL output from the controller and API access log. Keep test tag identifiers private and do not use a vehicle barrier. Record the board, firmware hash, power supply, router conditions, trial operator and UTC start/end times with every run.

## Trial procedure

- **RFID and API:** perform 30 entry/exit cycles using a dedicated tag. Record expected scan, read result, HTTP status, assigned slot and failure reason. Report successes/trials and latency mean, median, standard deviation and p95.
- **LED correctness:** for each slot, record expected free/occupied state and independently observed LED output.
- **Wi-Fi recovery:** record disconnect and restored-service timestamps over 10 controlled outages.
- **Servo command timing:** compare RFID detection, authorization response and GPIO command timestamps. Use an external sensor or video timing only if available to measure physical arm travel; command time is not travel time.
- **Power:** use a suitable inline meter on each supply rail. Do not infer servo current from ESP32 USB current.
- **Memory:** preserve free-heap telemetry from the controller serial stream.

Use `python -m scripts.hardware_evaluation capture --port PORT --output output/hardware/run.jsonl` and summarize with `python -m scripts.hardware_evaluation summarize --input output/hardware/run.jsonl --output-directory output/hardware/summary`. Untested measurements must remain `NOT TESTED`; estimates must not be described as measured.
