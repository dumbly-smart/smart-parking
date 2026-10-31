# Integration and physical test checklist

Software checks cover API and simulated behavior. Physical measures are reported separately and remain `NOT TESTED` where no observation was recorded.

| Scenario | Software evidence / safe procedure | Physical status |
|---|---|---|
| Valid RFID entry | Lifecycle integration checks; use one dedicated test tag | Two successful transaction samples recorded |
| Malformed RFID reading | API validation checks; reader-level malformed input needs a board trial | Not tested |
| Repeated RFID detection | Controller waits for tag removal and persists its idempotency key | Not independently measured |
| Multiple vehicle entries | Backend lifecycle checks; fill one slot at a time | Not tested |
| Full capacity | Backend returns structured capacity error; controller keeps gate closed | Not tested physically |
| Vehicle exit | Exit API checks; use an active test session | Two transaction samples recorded |
| Wi-Fi loss/recovery | Controller reconnect loop; use a controlled access-point interruption | Not tested |
| Backend timeout / invalid response | Bounded timeout, retry, and response validation leave gate closed | Software behavior only |
| Controller restart | Pending request persists in NVS; test with servo arm detached | Not tested |
| Dashboard synchronization | API status and event stream drive the software demo | Software behavior only |
| Servo safety | Confirmed allocation precedes the single gate command | Physical travel not independently measured |
| OLED updates | Firmware screens cover initialization, status, assignment, and errors | Not independently verified |

The host prediction smoke test loaded the saved GRU artifact and returned `model=gru`, `fallback_reason=null`, and occupancy ratio `0.136493` for the synthetic timeline. It is a software measurement, not a controller measurement.

Run `python -m pytest` for software checks. Keep the actuator unloaded for initial bench work and use a suitable regulated supply.
