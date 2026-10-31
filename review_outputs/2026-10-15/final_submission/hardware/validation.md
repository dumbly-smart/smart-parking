# Hardware connection and validation

This guide covers the ESP32 DevKit, RC522, SSD1306, five LEDs and the tabletop SG90 gate. Pin assignments are taken from controller firmware and listed in `pin_connections.csv`. The exported diagrams are proposed connection documents, not proof of physical continuity.

## Power and wiring

- Power RC522 and compatible OLED logic at 3.3 V.
- Connect RC522 SPI to GPIO 18/19/23, SS to GPIO 5, and reset to GPIO 4.
- Connect OLED SDA/SCL to GPIO 21/22.
- Connect each LED through its own 330 Ω resistor to GPIO 25, 26, 27, 32, or 33; connect LED cathodes to ground.
- Connect servo signal to GPIO 14. Feed servo power from a separate regulated 5 V supply and share ground with the controller. Never feed servo current through a GPIO or 3.3 V pin.

## Repeatable functional check

1. Build with `make firmware-controller` and start the local API.
2. Confirm `/health` and `/api/parking/status` return healthy state.
3. Scan a dedicated test tag once for entry. Confirm a slot assignment, the corresponding occupied status and LED command, and one authorized gate command.
4. Scan the same test tag for exit. Confirm the slot becomes free, its LED command turns off, and one gate close cycle is reported.
5. Repeat with a full lot, network loss, malformed response and controller restart; authorization failures must leave the gate closed.

The current report separates serial/API observations from physical LED visibility, mechanical servo travel, current draw and controlled Wi-Fi recovery measurements.
