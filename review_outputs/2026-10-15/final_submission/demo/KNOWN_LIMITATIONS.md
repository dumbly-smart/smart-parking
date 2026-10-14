# Known limitations

- No ESP32, ESP32-CAM, RC522, OLED, LEDs, servo, camera scene or assembled wiring was available for physical testing. Firmware compilation is not hardware validation.
- The pin map is a proposed ESP32 DevKit/WROOM-32 mapping and camera firmware explicitly targets AI-Thinker ESP32-CAM. Confirm exact board revisions before wiring.
- Backend hardware endpoints have no authentication layer. Keep them on a trusted local network and never expose them publicly.
- The camera uses a fixed-ROI edge-density heuristic. No labeled real-camera dataset or classification-quality measurement exists.
- The forecasting corpus is deterministic synthetic data. The models run on the server; no ESP32 inference, power or real-time hardware benchmark is claimed.
- Gate operation is a hobby-servo demonstration only, not a safety-rated barrier. Power loss cannot guarantee a mechanical closed position.
- The professor's base paper template was not present in the repository; the generated report is a conventional single-column academic format.
- The available Drive link is institution-restricted, as documented in the experimental report. Confirm reviewer access through VIT accounts.
