#include <Arduino.h>
#include <WebServer.h>
#include <WiFi.h>
#include <esp_camera.h>

#include "camera_board.h"

#if __has_include("local_config.h")
#include "local_config.h"
#else
static constexpr char WIFI_SSID[] = "";
static constexpr char WIFI_PASSWORD[] = "";
static constexpr int CAMERA_FRAME_SIZE = 8;
static constexpr int CAMERA_JPEG_QUALITY = 12;
#endif

namespace {
WebServer server(80);
bool cameraReady = false;
bool serverStarted = false;
uint32_t lastWifiAttemptMs = 0;
uint32_t lastCameraRetryMs = 0;
constexpr uint32_t kReconnectMs = 5000;
constexpr uint32_t kCameraRetryMs = 10000;
constexpr size_t kMaximumJpegBytes = 5 * 1024 * 1024;

bool initializeCamera() {
  camera_config_t config = {};
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = CameraPins::Y2;
  config.pin_d1 = CameraPins::Y3;
  config.pin_d2 = CameraPins::Y4;
  config.pin_d3 = CameraPins::Y5;
  config.pin_d4 = CameraPins::Y6;
  config.pin_d5 = CameraPins::Y7;
  config.pin_d6 = CameraPins::Y8;
  config.pin_d7 = CameraPins::Y9;
  config.pin_xclk = CameraPins::Xclk;
  config.pin_pclk = CameraPins::Pclk;
  config.pin_vsync = CameraPins::Vsync;
  config.pin_href = CameraPins::Href;
  config.pin_sccb_sda = CameraPins::Siod;
  config.pin_sccb_scl = CameraPins::Sioc;
  config.pin_pwdn = CameraPins::Pwdn;
  config.pin_reset = CameraPins::Reset;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size = static_cast<framesize_t>(CAMERA_FRAME_SIZE);
  config.jpeg_quality = constrain(CAMERA_JPEG_QUALITY, 8, 40);
  config.fb_count = psramFound() ? 2 : 1;
  config.grab_mode = psramFound() ? CAMERA_GRAB_LATEST : CAMERA_GRAB_WHEN_EMPTY;
  config.fb_location = psramFound() ? CAMERA_FB_IN_PSRAM : CAMERA_FB_IN_DRAM;

  const esp_err_t error = esp_camera_init(&config);
  if (error != ESP_OK) {
    Serial.printf("Camera initialization failed (0x%x); retrying later\n", error);
    return false;
  }
  sensor_t *sensor = esp_camera_sensor_get();
  if (sensor != nullptr) sensor->set_framesize(sensor, static_cast<framesize_t>(CAMERA_FRAME_SIZE));
  return true;
}

void sendJson(int status, const char *message) {
  String body = "{\"status\":\"" + String(message) + "\",\"camera\":" +
                String(cameraReady ? "\"ready\"" : "\"unavailable\"") + "}";
  server.send(status, "application/json", body);
}

void handleHealth() {
  if (WiFi.status() != WL_CONNECTED) {
    sendJson(503, "wifi_disconnected");
    return;
  }
  if (!cameraReady) {
    sendJson(503, "camera_unavailable");
    return;
  }
  String body = "{\"status\":\"ok\",\"camera\":\"ready\",\"ip\":\"" +
                WiFi.localIP().toString() + "\"}";
  server.send(200, "application/json", body);
}

void handleCapture() {
  if (WiFi.status() != WL_CONNECTED || !cameraReady) {
    sendJson(503, "camera_unavailable");
    return;
  }
  camera_fb_t *frame = esp_camera_fb_get();
  if (frame == nullptr) {
    sendJson(503, "capture_failed");
    return;
  }
  if (frame->format != PIXFORMAT_JPEG || frame->len == 0 || frame->len > kMaximumJpegBytes) {
    esp_camera_fb_return(frame);
    sendJson(500, "invalid_camera_frame");
    return;
  }
  server.sendHeader("Cache-Control", "no-store, max-age=0");
  server.sendHeader("X-Content-Type-Options", "nosniff");
  server.setContentLength(frame->len);
  server.send(200, "image/jpeg", "");
  const size_t written = server.client().write(frame->buf, frame->len);
  esp_camera_fb_return(frame);
  if (written == 0) Serial.println("Snapshot client disconnected before JPEG transfer completed");
}

void handleNotFound() { sendJson(404, "not_found"); }

void connectWifi() {
  if (WIFI_SSID[0] == '\0') return;
  if (WiFi.status() == WL_CONNECTED) return;
  if (millis() - lastWifiAttemptMs < kReconnectMs && lastWifiAttemptMs != 0) return;
  lastWifiAttemptMs = millis();
  if (lastWifiAttemptMs < kReconnectMs) {
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  } else {
    WiFi.reconnect();
  }
  Serial.println("Wi-Fi connection unavailable; reconnect scheduled");
}
}  // namespace

void setup() {
  Serial.begin(115200);
  WiFi.mode(WIFI_STA);
  if (WIFI_SSID[0] == '\0') Serial.println("Wi-Fi credentials are empty; configure local_config.h");
  else WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  server.on("/health", HTTP_GET, handleHealth);
  server.on("/capture", HTTP_GET, handleCapture);
  server.onNotFound(handleNotFound);
  server.begin();
  serverStarted = true;
  cameraReady = initializeCamera();
  lastWifiAttemptMs = millis();
}

void loop() {
  connectWifi();
  if (serverStarted) server.handleClient();
  if (!cameraReady && millis() - lastCameraRetryMs >= kCameraRetryMs) {
    lastCameraRetryMs = millis();
    cameraReady = initializeCamera();
  }
  delay(2);
}
