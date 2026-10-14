# Hardware design and validation status

## Status and scope

This document describes a **proposed bench wiring** for an ESP32 DevKit V1
with an ESP32-WROOM-32 controller and an AI-Thinker ESP32-CAM/OV2640 module.
The repository design does not identify purchased board revisions. Confirm the
silkscreen and module datasheet before connecting power. No physical hardware
was attached for this software session, so no wiring, actuator, camera, Wi-Fi,
or electrical behavior is claimed as bench-tested.

The controller mapping avoids the ESP32 classic boot-strapping pins GPIO0, 2,
5, 12, and 15, flash connections GPIO6–11, and input-only GPIO34–39. GPIO18,
19, and 23 are allocated only to the RC522 SPI bus; GPIO21 and 22 to I²C;
GPIO25, 26, 27, 32, and 33 to LEDs; GPIO14 to the servo PWM signal. GPIO4
resets the reader. Confirm the exact DevKit board exposes these pins. The
mapping is a design review, not an electrical verification.

For the AI-Thinker board, camera GPIOs are reserved as defined in Espressif's
[camera pin map](https://github.com/espressif/esp32-camera/blob/master/examples/camera_example/main/camera_pinout.h).
The firmware requires `CAMERA_BOARD_AI_THINKER`; a different ESP32-CAM variant
must provide its own verified mapping. Espressif notes classic ESP32 GPIO34
and above are input-only and that GPIO strapping pins need care in its
[GPIO documentation](https://docs.espressif.com/projects/esp-idf/en/v5.1/esp32/api-reference/peripherals/gpio.html).

## Connection rules

- Power the RC522 and a 3.3-V-compatible OLED from the controller's 3V3 rail.
  Do not connect 5-V logic or OLED pull-ups to ESP32 GPIO.
- Put a 330 Ω series resistor on each LED. An LED is on when its status GPIO
  is high and the slot is accepted as occupied; off means accepted free. If
  API state is unknown, all five LEDs blink together to mean **unknown**, not
  free.
- The SG90 signal goes to GPIO14, while its positive lead uses a separate
  regulated 5-V supply with at least 1 A capability as an initial bench
  provision. Check the exact servo variant's stall-current specification.
  Join the negative rail to controller ground. Never source motor current from
  a GPIO or the controller's 3V3 regulator. Keep servo wiring short and add
  local bulk capacitance according to the servo/supply datasheets.
- Power the ESP32-CAM from a regulated supply connected to its board's labeled
  5-V input. Do not use the camera module's 3V3 pin as a supply input. Do not
  tie separate +5-V supplies together unless a designed power OR-ing scheme is
  used. Grounds must share a reference for the bench setup.
- Use the controller's USB supply separately from the servo supply. Avoid
  powering the board simultaneously through USB and its 5-V pin unless the
  exact carrier board documents safe source selection.
- A hobby servo is not a safety-rated barrier. Power loss can leave it at its
  last mechanical position. Keep the test gate lightweight, isolated, and
  manually supervised; do not connect it to a real traffic barrier.

## Bill of materials

| Qty. | Component | Purpose / notes |
| ---: | --- | --- |
| 1 | ESP32 DevKit V1 / ESP32-WROOM-32 | RFID, server API, display, status LEDs, servo signal; exact carrier revision TBD |
| 1 | AI-Thinker ESP32-CAM with OV2640 | JPEG snapshot service; confirm board variant and PSRAM |
| 1 | RC522 reader | SPI RFID reader; use 3.3-V supply and logic |
| 2–5 | RFID cards/tags | Test identities; treat UIDs as sensitive identifiers |
| 1 | SSD1306 I²C OLED | 128×64 status display; choose a 3.3-V logic-compatible module |
| 5 | LEDs | One indicator per configured parking slot |
| 5 | 330 Ω resistors | Per-LED current limiting |
| 1 | SG90 servo and lightweight model gate | Supervised tabletop demonstration only |
| 1 | Regulated 5-V, ≥1-A servo supply | Separate motor supply; check exact motor current specification |
| 1 | Regulated 5-V camera supply | Sized for camera board startup/capture current per its vendor sheet |
| 1 | USB cable / supply | Powers the controller board |
| As needed | Breadboard, jumpers, common-ground wiring | Keep SPI/I²C short; verify rails before attaching modules |

## Proposed wiring sequence

1. Keep all supplies disconnected. Confirm board variant and pin labels.
2. Connect RC522 SPI and reset pins from `pin_connections.csv`; connect its
   3V3 and GND only.
3. Connect the OLED to GPIO21/22 and 3V3/GND. Confirm the module does not pull
   SDA/SCL to 5 V.
4. Connect each LED through its own 330 Ω resistor to the listed GPIO; connect
   each cathode to common ground.
5. Connect servo signal to GPIO14. Keep servo +5 V disconnected. Join servo
   supply negative to common ground, then connect its regulated positive rail
   to the servo only.
6. Connect the camera to its separate regulated supply at the labeled 5-V/GND
   pins. Join grounds, but keep the separate +5-V rails isolated.
7. With no RFID or servo connected, power the controller over USB and inspect
   boot. Then test RFID/OLED/LED modules. Attach the servo last and run only the
   contained, lightweight gate fixture.
8. Verify one function at a time and record the board/module revision and
   supply measurements in the physical checklist.

## Calibration and troubleshooting

Run `python -m scripts.calibrate_camera_rois --camera-url http://CAMERA-IP/capture`
on a host with a graphical desktop. The tool captures and validates one JPEG,
lets the operator draw one non-overlapping region per configured slot, writes
`config/rois.json`, and saves an overlay at `data/parking_roi_overlay.png`.
These local files are ignored by Git. Set
`SMART_PARKING_ROI_CONFIG_PATH=config/rois.json` before starting the backend.
Use a fixed camera mount and ensure the saved boxes cover each marked space,
not moving aisles, shadows, or unrelated scene content. The configured
edge-density heuristic is only a baseline and requires site-specific threshold
validation.

| Symptom | Check |
| --- | --- |
| Controller cannot boot | Disconnect anything on strap pins; confirm 3V3 and ground polarity; check board revision |
| RC522 not detected | Check 3V3, SPI SCK/MISO/MOSI, chip select GPIO13, reset GPIO4, and short wiring |
| OLED blank | Check I²C address 0x3C, SDA21/SCL22, 3.3-V-compatible pull-ups |
| Servo resets controller | Separate servo power, common ground, supply current, bulk decoupling, no motor power from GPIO |
| Camera `/health` reports unavailable | Check board variant, 5-V rail, camera flex cable seating, PSRAM, and startup logs |
| Camera frame gives ROI error | Recapture at configured frame size and recalibrate ROIs |
| LED appears free during outage | Firmware blinks all LEDs when status is unknown; do not interpret that as occupancy |

## Physical test evidence

All tests in `review_outputs/2026-10-15/final_submission/demo/TEST_CHECKLIST.md`
are marked with their evidence class. Firmware compilation and software API
tests are not substitutes for a real electrical or mechanical test.
