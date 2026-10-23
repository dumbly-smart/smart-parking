# Firmware build and operation

## Board targets and secrets

Both PlatformIO projects are compile-targeted as an ESP32 DevKit (`esp32dev`)
and an AI-Thinker ESP32-CAM (`esp32cam`). The physical board labels remain to
be confirmed. Firmware defaults have empty Wi-Fi credentials; no secret is
checked in. Copy each `include/local_config.example.h` to `include/local_config.h`
and enter local Wi-Fi credentials and the server's private LAN address. The
local files are ignored by Git. This workstation currently has private, mode-0600
local configs populated from its active Wi-Fi profile; those values are not part
of the repository.

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

The hardware API is run as a user systemd service at `10.42.115.131:8001`,
bound only to the current Wi-Fi interface. It shares the default SQLite database
with the development dashboard on `127.0.0.1:8000`. A local random bearer token
protects `/api/*`; `/health` remains public. The ignored controller config and
`output/hardware/device-api.env` hold the token with mode 0600. The camera poller
reads `SMART_PARKING_DEVICE_API_TOKEN` and sends the token only to the backend.
For a new machine, configure a new token in the server environment and
`DEVICE_API_TOKEN` in controller `local_config.h`; never commit either value.

The API uses HTTP, not TLS. Keep the service on a trusted private network and
do not publish it to the internet or use untrusted Wi-Fi. The controller sends
RFID UIDs in the API request body, does not print them, and should be used only
on an isolated prototype network. The current Wi-Fi address can change; update
the controller URL and user service bind address together if it does.

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
  --backend-url http://SERVER-LAN-IP:8001 \
  --interval-seconds 5
```

Load the local token into the shell environment before starting the poller; it
will attach bearer authorization only to backend requests. Use `--once` for a
single-frame smoke test. The ingest process allows one
in-flight request and exponentially backs off on errors up to 60 seconds.
Clean shutdown is via Ctrl-C or SIGTERM.
