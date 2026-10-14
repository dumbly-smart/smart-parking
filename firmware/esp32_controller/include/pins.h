#pragma once

#include <Arduino.h>

namespace Pins {
constexpr uint8_t RfidSck = 18;
constexpr uint8_t RfidMiso = 19;
constexpr uint8_t RfidMosi = 23;
constexpr uint8_t RfidSs = 13;
constexpr uint8_t RfidReset = 4;

constexpr uint8_t I2cSda = 21;
constexpr uint8_t I2cScl = 22;
constexpr uint8_t OledAddress = 0x3C;

constexpr uint8_t SlotLeds[] = {25, 26, 27, 32, 33};
constexpr size_t SlotCount = sizeof(SlotLeds) / sizeof(SlotLeds[0]);
constexpr uint8_t GateServo = 14;
}  // namespace Pins
