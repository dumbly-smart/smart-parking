# Firmware build and operation

## Board targets and secrets

Both PlatformIO projects are compile-targeted as an ESP32 DevKit (`esp32dev`)
and an AI-Thinker ESP32-CAM (`esp32cam`). The physical board labels remain to
be confirmed. Firmware defaults have empty Wi-Fi credentials; no secret is
checked in. Copy each `include/local_config.example.h` to `include/local_config.h`
and enter local Wi-Fi credentials and the server's private LAN address. The
local files are ignored by Git.

Host compilation was verified with PlatformIO on 14 October 2026. The controller
image used 27,220 bytes RAM and 474,549 bytes flash; the AI-Thinker camera image
used 49,628 bytes RAM and 836,777 bytes flash. This confirms source compatibility
with the selected targets, not successful flashing or physical operation.

```bash
python -m pip install platformio
cp firmware/esp32_controller/include/local_config.example.h firmware/esp32_controller/include/local_config.h
cp firmware/esp32_cam/include/local_config.example.h firmware/esp32_cam/include/local_config.h
pio run -d firmware/esp32_controller
pio run -d firmware/esp32_cam
pio device monitor -d firmware/esp32_controller -b 115200
```

Keep the FastAPI service on a trusted local network. The existing API has no
device authentication or TLS configuration, so do not publish it to the
internet or use an untrusted Wi-Fi network. The controller sends RFID UIDs in
the API request body, does not print them, and should be used only on an
isolated prototype network.

## Controller flow

The firmware reads and normalizes an RC522 UID in memory. It queries parking
status to decide whether the UID has an active session, then posts to the
existing entry or exit endpoint. It persists a monotonic idempotency key and
pending payload in NVS before sending. Timeout/reboot retries reuse the same
key. The response UID and `gate_action` must validate, and the subsequent
server status must confirm the entry or exit before any gate movement. The
gate's actuation flag is stored before moving; reboot recovery will not repeat
the motion. Network errors, full capacity, malformed replies, and unconfirmed
state all leave the gate closed.

Entry/exit selection uses the UID field already returned by the current status
API. That API is intended for trusted LAN use. Do not add UID values to serial
logs. An active RFID card must be removed before another tap; a held card is
latched until the reader observes a 500-ms no-card interval.

## ESP32-CAM

The camera board starts a small HTTP service: `GET /health` returns JSON and
`GET /capture` returns one bounded JPEG. It uses the AI-Thinker OV2640 pin map,
VGA resolution and JPEG quality 12 by default, with PSRAM-aware buffering. It
does not upload directly to the backend; the Python poller provides retry,
backpressure, JPEG validation, and the existing multipart API contract.

```bash
python -m scripts.camera_ingest \
  --camera-url http://CAMERA-IP/capture \
  --backend-url http://SERVER-LAN-IP:8000 \
  --interval-seconds 5
```

Use `--once` for a single-frame smoke test. The ingest process allows one
in-flight request and exponentially backs off on errors up to 60 seconds.
Clean shutdown is via Ctrl-C or SIGTERM.
