# Integration and physical test checklist

Software automation confirms API and simulated behavior only. No hardware was attached, so every physical observation below remains **NOT TESTED**.

| Scenario | Software evidence / safe procedure | Physical status |
|---|---|---|
| Valid RFID entry | Existing lifecycle integration tests; later bench-test with one allowlisted tag | Not tested |
| Malformed RFID reading | API validation tests; reader-level malformed UID needs board test | Not tested |
| Repeated RFID detection | Controller waits for card removal and persists the pending idempotency key | Not tested |
| Multiple vehicle entries | Backend concurrent lifecycle tests; fill one slot at a time | Not tested |
| Full capacity | Backend returns structured capacity error; controller leaves gate closed | Not tested |
| Vehicle exit | Existing exit API tests; use same tag after an active session | Not tested |
| Wi-Fi loss/recovery | Controller reconnect loop; disconnect AP only with servo detached | Not tested |
| Backend timeout | Bounded HTTP timeout and retry preserving operation key | Not tested |
| ESP32 restart | Pending request stored in Preferences; test after servo is disconnected | Not tested |
| Invalid server response | Strict JSON/status validation rejects response; gate remains closed | Not tested |
| Camera disconnection | Ingestion poller bounded retry; camera firmware retries Wi-Fi/camera init | Not tested physically |
| Occupancy transitions | Existing JPEG endpoint/database tests and synthetic demo; calibrate on real view | Not tested physically |
| Servo safety | Startup closed command and confirmed allocation before opening; inspect unloaded on isolated bench | Not tested |
| OLED updates | Firmware screens cover initialization, status, assignment and errors | Not tested |
| Dashboard sync | Backend route and dashboard tests; software demo refreshes persisted status | Not tested physically |

The local API inference smoke used a copy of the review database and the saved
GRU artifact. It returned `model=gru`, `fallback_reason=null`, and occupancy
ratio `0.136493` for the prepared synthetic timeline. This verifies server-side
artifact loading and inference on the host; it is not a hardware measurement.

Run `python -m pytest` for automated software checks. Keep a human operator at the isolated bench, detach the barrier arm, and use a current-limited supply for initial actuator checks.
