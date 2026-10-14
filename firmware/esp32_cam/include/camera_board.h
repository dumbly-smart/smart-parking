#pragma once

// Mapping is for the AI-Thinker ESP32-CAM (OV2640) reference board only.
// Other ESP32-CAM boards must add and explicitly select their own map.
#if !defined(CAMERA_BOARD_AI_THINKER)
#error "Select a verified ESP32-CAM variant; CAMERA_BOARD_AI_THINKER is required"
#endif

namespace CameraPins {
constexpr int Pwdn = 32;
constexpr int Reset = -1;
constexpr int Xclk = 0;
constexpr int Siod = 26;
constexpr int Sioc = 27;
constexpr int Y9 = 35;
constexpr int Y8 = 34;
constexpr int Y7 = 39;
constexpr int Y6 = 36;
constexpr int Y5 = 21;
constexpr int Y4 = 19;
constexpr int Y3 = 18;
constexpr int Y2 = 5;
constexpr int Vsync = 25;
constexpr int Href = 23;
constexpr int Pclk = 22;
}  // namespace CameraPins
