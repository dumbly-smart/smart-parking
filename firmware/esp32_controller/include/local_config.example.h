#pragma once

// Copy to local_config.h and set values on the trusted local network.
// Never expose the backend control API to the public internet.
static constexpr char WIFI_SSID[] = "";
static constexpr char WIFI_PASSWORD[] = "";
static constexpr char BACKEND_BASE_URL[] = "http://192.168.1.10:8000";

static constexpr int SERVO_CLOSED_DEGREES = 10;
static constexpr int SERVO_OPEN_DEGREES = 85;
static constexpr uint32_t GATE_OPEN_MILLISECONDS = 2500;
static constexpr uint32_t STATUS_POLL_MILLISECONDS = 10000;
