# Controller firmware and network setup

The project uses an ESP32 DevKit controller with an RC522 RFID reader, SSD1306 display, five slot LEDs and a supervised tabletop servo. The firmware source of truth for GPIO mapping is `firmware/esp32_controller/include/pins.h`.

## Build and flash

```bash
make firmware-controller
```

Set Wi-Fi credentials and the local API endpoint in the private controller configuration, then build and flash with PlatformIO. Do not commit private configuration or credentials. The controller retries Wi-Fi/API operations, persists pending idempotency keys, and keeps the gate closed on failed, malformed or uncertain responses.

## Electrical limits

RC522 logic is 3.3 V. Each indicator LED has an individual 330 Ω series resistor. Power the servo from a separate regulated supply sized for the exact unit; connect its ground to controller ground. Never power the servo from a GPIO or the 3.3 V rail. The servo is for a supervised tabletop model only.
