#include <Arduino.h>
#include <Adafruit_SSD1306.h>
#include <ArduinoJson.h>
#include <ESP32Servo.h>
#include <HTTPClient.h>
#include <MFRC522.h>
#include <Preferences.h>
#include <SPI.h>
#include <WiFi.h>

#include "pins.h"

#if __has_include("local_config.h")
#include "local_config.h"
#else
static constexpr char WIFI_SSID[] = "";
static constexpr char WIFI_PASSWORD[] = "";
static constexpr char BACKEND_BASE_URL[] = "http://192.168.1.10:8000";
static constexpr int SERVO_CLOSED_DEGREES = 10;
static constexpr int SERVO_OPEN_DEGREES = 85;
static constexpr uint32_t GATE_OPEN_MILLISECONDS = 2500;
static constexpr uint32_t STATUS_POLL_MILLISECONDS = 10000;
#endif

namespace {
constexpr uint32_t kHttpTimeoutMs = 3500;
constexpr uint32_t kWifiRetryMs = 5000;
constexpr uint32_t kCardRemovalMs = 500;
constexpr uint32_t kRetryInitialMs = 1000;
constexpr uint32_t kRetryMaximumMs = 30000;

Adafruit_SSD1306 display(128, 64, &Wire, -1);
MFRC522 rfid(Pins::RfidSs, Pins::RfidReset);
Servo gateServo;
Preferences preferences;

struct SlotState {
  bool occupied[5] = {false, false, false, false, false};
  bool known = false;
  String names[5];
};

SlotState slotState;
bool displayReady = false;
bool storageReady = false;
bool gateReady = false;
bool wifiStarted = false;
bool wifiWasConnected = false;
uint32_t wifiDisconnectedAtMs = 0;
bool cardArmed = true;
bool absenceTiming = false;
uint32_t absentSinceMs = 0;
uint32_t lastWifiAttemptMs = 0;
uint32_t lastStatusMs = 0;
uint32_t nextRetryMs = 0;
uint32_t retryDelayMs = kRetryInitialMs;
bool gateOpen = false;
uint32_t gateCloseAtMs = 0;
bool pendingOperation = false;
bool pendingGateDone = false;
uint8_t telemetryMask = 0;
uint8_t telemetryAck = 0;
uint32_t nextTelemetryMs = 0;
String pendingUid;
String pendingKey;
String pendingType;
String assignedSlotName;
int assignedSlotId = 0;
String lastMessage = "Starting";
uint32_t scanReceivedAtMs = 0;

struct HttpResult {
  int code = 0;
  String body;
};

void emitMetric(const char *event, const char *operation = nullptr, bool hasSuccess = false,
                bool success = false, uint32_t latencyMs = 0, int httpStatus = 0) {
  JsonDocument metric;
  metric["event"] = event;
  metric["uptime_ms"] = millis();
  if (operation) metric["operation"] = operation;
  if (hasSuccess) metric["success"] = success;
  if (latencyMs) metric["latency_ms"] = latencyMs;
  if (httpStatus) metric["http_status"] = httpStatus;
  metric["free_heap_bytes"] = ESP.getFreeHeap();
  serializeJson(metric, Serial);
  Serial.println();
}

void showMessage(const String &title, const String &line1 = "", const String &line2 = "") {
  lastMessage = title;
  Serial.println(title);  // Never log RFID values, request bodies, or credentials.
  if (!displayReady) return;
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.println("SMART PARKING");
  display.setTextSize(1);
  display.println(title);
  if (line1.length()) display.println(line1);
  if (line2.length()) display.println(line2);
  display.display();
}

String normalizedUid(const MFRC522::Uid &uid) {
  String value;
  value.reserve(uid.size * 2);
  char byteText[3];
  for (byte index = 0; index < uid.size; ++index) {
    snprintf(byteText, sizeof(byteText), "%02X", uid.uidByte[index]);
    value += byteText;
  }
  return value;
}

String uppercase(String value) {
  value.toUpperCase();
  return value;
}

String backendUrl(const char *path) {
  String base(BACKEND_BASE_URL);
  while (base.endsWith("/")) base.remove(base.length() - 1);
  return base + path;
}

byte readRfidVersionAtLowClock() {
  SPI.beginTransaction(SPISettings(250000, MSBFIRST, SPI_MODE0));
  digitalWrite(Pins::RfidSs, LOW);
  SPI.transfer(0x80 | ((MFRC522::VersionReg << 1) & 0x7E));
  const byte version = SPI.transfer(0x00);
  digitalWrite(Pins::RfidSs, HIGH);
  SPI.endTransaction();
  return version;
}

HttpResult requestHttp(const String &url, const String &method, const String &body = "",
                       uint32_t timeoutMs = kHttpTimeoutMs) {
  HttpResult result;
  HTTPClient http;
  WiFiClient network;
  http.setTimeout(timeoutMs);
  if (!http.begin(network, url)) return result;
  http.addHeader("Accept", "application/json");
  if (DEVICE_API_TOKEN[0] != '\0')
    http.addHeader("Authorization", String("Bearer ") + DEVICE_API_TOKEN);
  if (method == "POST") http.addHeader("Content-Type", "application/json");
  result.code = method == "POST" ? http.POST(body) : http.GET();
  if (result.code > 0) {
    const int contentLength = http.getSize();
    if (contentLength > 0 && contentLength <= 16384) result.body = http.getString();
  }
  http.end();
  return result;
}

bool checkHealth() {
  HttpResult response = requestHttp(backendUrl("/health"), "GET");
  if (response.code != HTTP_CODE_OK) return false;
  JsonDocument document;
  if (deserializeJson(document, response.body) != DeserializationError::Ok) return false;
  return document["status"].is<const char *>() &&
         String(document["status"].as<const char *>()) == "ok";
}

void setUnknownLeds() {
  slotState.known = false;
}

void refreshLeds() {
  const bool blink = ((millis() / 400) % 2) == 0;
  for (size_t index = 0; index < Pins::SlotCount; ++index) {
    const bool on = slotState.known ? slotState.occupied[index] : blink;
    digitalWrite(Pins::SlotLeds[index], on ? HIGH : LOW);
  }
}

bool parseStatus(const String &body, SlotState &result) {
  JsonDocument document;
  if (deserializeJson(document, body) != DeserializationError::Ok) return false;
  JsonArray slots = document["slots"].as<JsonArray>();
  if (slots.isNull() || slots.size() != Pins::SlotCount) return false;
  bool seen[5] = {false, false, false, false, false};
  for (JsonObject slot : slots) {
    const int id = slot["id"] | 0;
    if (id < 1 || id > static_cast<int>(Pins::SlotCount) || seen[id - 1] ||
        !slot["occupied"].is<bool>() || !slot["name"].is<const char *>()) return false;
    seen[id - 1] = true;
    result.occupied[id - 1] = slot["occupied"].as<bool>();
    result.names[id - 1] = slot["name"].as<String>();
  }
  result.known = true;
  return true;
}

bool fetchStatus(SlotState &result) {
  if (WiFi.status() != WL_CONNECTED) return false;
  HttpResult response = requestHttp(backendUrl("/api/parking/status"), "GET");
  if (response.code != HTTP_CODE_OK || !parseStatus(response.body, result)) return false;
  return true;
}

bool activeSessionForUid(const String &body, const String &uid, int *slotId = nullptr) {
  JsonDocument document;
  if (deserializeJson(document, body) != DeserializationError::Ok) return false;
  JsonArray slots = document["slots"].as<JsonArray>();
  if (slots.isNull()) return false;
  for (JsonObject slot : slots) {
    if (!slot["rfid_uid"].is<const char *>()) continue;
    if (uppercase(slot["rfid_uid"].as<String>()) == uid) {
      if (slotId) *slotId = slot["id"] | 0;
      return true;
    }
  }
  return false;
}

bool statusForUid(const String &uid, bool &parked) {
  HttpResult response = requestHttp(backendUrl("/api/parking/status"), "GET");
  if (response.code != HTTP_CODE_OK) return false;
  SlotState parsed;
  if (!parseStatus(response.body, parsed)) return false;
  parked = activeSessionForUid(response.body, uid);
  slotState = parsed;
  refreshLeds();
  return true;
}

bool persistPending() {
  if (!storageReady || preferences.putString("uid", pendingUid) == 0 ||
      preferences.putString("key", pendingKey) == 0 ||
      preferences.putString("type", pendingType) == 0 ||
      preferences.putBool("gate_done", pendingGateDone) != 1 ||
      preferences.putUChar("telemetry", telemetryMask) != 1 ||
      preferences.putUChar("telemetry_ack", telemetryAck) != 1 ||
      preferences.putBool("pending", true) != 1) return false;
  pendingOperation = true;
  return true;
}

void clearPending() {
  if (!storageReady) return;
  preferences.putBool("pending", false);
  preferences.remove("uid");
  preferences.remove("key");
  preferences.remove("type");
  preferences.putBool("gate_done", false);
  preferences.putUChar("telemetry", 0);
  preferences.putUChar("telemetry_ack", 0);
  pendingUid = "";
  pendingKey = "";
  pendingType = "";
  pendingOperation = false;
  pendingGateDone = false;
  telemetryMask = 0;
  telemetryAck = 0;
  assignedSlotId = 0;
  assignedSlotName = "";
  retryDelayMs = kRetryInitialMs;
}

String newIdempotencyKey() {
  const uint32_t sequence = preferences.getUInt("seq", 0) + 1;
  if (!storageReady || preferences.putUInt("seq", sequence) != sizeof(sequence)) return "";
  char key[64];
  snprintf(key, sizeof(key), "esp32-%012llx-%lu",
           static_cast<unsigned long long>(ESP.getEfuseMac()),
           static_cast<unsigned long>(sequence));
  return String(key);
}

bool beginOperation(const String &uid, const String &operation) {
  if (!storageReady) return false;
  pendingUid = uid;
  pendingKey = newIdempotencyKey();
  if (!pendingKey.length()) return false;
  pendingType = operation;
  scanReceivedAtMs = millis();
  pendingGateDone = false;
  telemetryMask = 1;
  telemetryAck = 0;
  if (!persistPending()) {
    pendingUid = "";
    pendingKey = "";
    pendingType = "";
    return false;
  }  // Persist before POST, so retries and reboots reuse this exact key.
  nextRetryMs = millis();
  return true;
}

bool verifyEntryCommit(const String &uid, int expectedSlotId) {
  HttpResult status = requestHttp(backendUrl("/api/parking/status"), "GET");
  if (status.code != HTTP_CODE_OK) return false;
  int actualSlotId = 0;
  if (!activeSessionForUid(status.body, uid, &actualSlotId) || actualSlotId != expectedSlotId)
    return false;
  SlotState parsed;
  if (!parseStatus(status.body, parsed)) return false;
  slotState = parsed;
  refreshLeds();
  return true;
}

bool verifyExitCommit(const String &uid) {
  HttpResult status = requestHttp(backendUrl("/api/parking/status"), "GET");
  if (status.code != HTTP_CODE_OK) return false;
  JsonDocument document;
  if (deserializeJson(document, status.body) != DeserializationError::Ok) return false;
  JsonArray slots = document["slots"].as<JsonArray>();
  if (slots.isNull()) return false;
  for (JsonObject slot : slots) {
    if (slot["rfid_uid"].is<const char *>() &&
        uppercase(slot["rfid_uid"].as<String>()) == uid) return false;
  }
  SlotState parsed;
  if (!parseStatus(status.body, parsed)) return false;
  slotState = parsed;
  refreshLeds();
  return true;
}

bool openGateOnce() {
  if (pendingGateDone) return true;
  if (!storageReady || !gateReady || preferences.putBool("gate_done", true) != 1) return false;
  // Mark before moving: a reset can fail safe closed, but cannot replay the actuation.
  pendingGateDone = true;
  gateServo.write(SERVO_OPEN_DEGREES);
  gateOpen = true;
  gateCloseAtMs = millis() + GATE_OPEN_MILLISECONDS;
  emitMetric("gate_command", pendingType.c_str(), false, false,
             millis() - scanReceivedAtMs);
  telemetryMask |= 2;
  preferences.putUChar("telemetry", telemetryMask);
  return true;
}

void flushTelemetry() {
  if (!pendingOperation || WiFi.status() != WL_CONNECTED ||
      static_cast<int32_t>(millis() - nextTelemetryMs) < 0) return;
  for (uint8_t phase = 1; phase <= 4; phase <<= 1) {
    if (!(telemetryMask & phase) || (telemetryAck & phase)) continue;
    JsonDocument payload;
    payload["event_type"] = phase == 1 ? "rfid_read" : phase == 2 ? "gate_opened" : "gate_closed";
    payload["operation"] = pendingType;
    payload["operation_key"] = pendingKey;
    payload["rfid_uid"] = pendingUid;
    String encoded;
    serializeJson(payload, encoded);
    const HttpResult result = requestHttp(backendUrl("/api/parking/hardware-events"), "POST", encoded,
                                          gateOpen ? 350 : kHttpTimeoutMs);
    if (result.code != HTTP_CODE_OK && result.code != HTTP_CODE_CREATED) {
      nextTelemetryMs = millis() + 1000;
      return;
    }
    telemetryAck |= phase;
    preferences.putUChar("telemetry_ack", telemetryAck);
  }
  if (pendingGateDone && !gateOpen && (telemetryMask & 4) &&
      (telemetryAck & telemetryMask) == telemetryMask) clearPending();
}

void processPendingOperation() {
  if (!pendingOperation || gateOpen || !storageReady || WiFi.status() != WL_CONNECTED ||
      static_cast<int32_t>(millis() - nextRetryMs) < 0) return;
  if (pendingGateDone || !(telemetryAck & 1)) return;

  JsonDocument request;
  request["rfid_uid"] = pendingUid;
  request["idempotency_key"] = pendingKey;
  request["source"] = "controller";
  String encoded;
  serializeJson(request, encoded);
  const char *path = pendingType == "entry" ? "/api/vehicle/entry" : "/api/vehicle/exit";
  const uint32_t requestStartedMs = millis();
  HttpResult response = requestHttp(backendUrl(path), "POST", encoded);
  emitMetric("api_transaction", pendingType.c_str(), true,
             response.code == HTTP_CODE_OK || response.code == HTTP_CODE_CREATED,
             millis() - requestStartedMs, response.code);

  if (response.code == HTTP_CODE_OK || response.code == HTTP_CODE_CREATED) {
    JsonDocument result;
    if (deserializeJson(result, response.body) != DeserializationError::Ok ||
        !result["rfid_uid"].is<const char *>() ||
        uppercase(result["rfid_uid"].as<String>()) != pendingUid ||
        String(result["gate_action"] | "") != "open") {
      showMessage("Invalid server reply", "Gate remains closed", "Retrying safely");
      nextRetryMs = millis() + retryDelayMs;
      retryDelayMs = min(retryDelayMs * 2, kRetryMaximumMs);
      return;
    }

    bool committed = false;
    if (pendingType == "entry") {
      const int slotId = result["slot_id"] | 0;
      const String slotName = result["slot_name"] | "";
      if (slotId >= 1 && slotId <= static_cast<int>(Pins::SlotCount) && slotName.length() &&
          verifyEntryCommit(pendingUid, slotId)) {
        assignedSlotId = slotId;
        assignedSlotName = slotName;
        committed = true;
        showMessage("Entry successful", "Assigned " + slotName);
      }
    } else if (pendingType == "exit" && verifyExitCommit(pendingUid)) {
      committed = true;
      showMessage("Exit successful", "Session closed");
    }
    if (!committed) {
      showMessage("Commit unverified", "Gate remains closed", "Retrying same request");
      nextRetryMs = millis() + retryDelayMs;
      retryDelayMs = min(retryDelayMs * 2, kRetryMaximumMs);
      return;
    }

    if (!pendingGateDone && !openGateOnce()) {
      showMessage("Storage/gate error", "Gate remains closed", "Retrying safely");
      nextRetryMs = millis() + retryDelayMs;
      retryDelayMs = min(retryDelayMs * 2, kRetryMaximumMs);
    }
    return;
  }

  if (response.code >= 400 && response.code < 500 && response.code != HTTP_CODE_REQUEST_TIMEOUT) {
    if (response.code == 409 && pendingType == "entry")
      showMessage("Parking full", "No slot assigned", "Gate remains closed");
    else showMessage("Request rejected", "HTTP " + String(response.code), "Gate remains closed");
    clearPending();
    return;
  }

  showMessage("Network/server error", "HTTP " + String(response.code), "Retrying same key");
  nextRetryMs = millis() + retryDelayMs;
  retryDelayMs = min(retryDelayMs * 2, kRetryMaximumMs);
}

bool cardStillOnReader() {
  byte atqa[2];
  byte atqaSize = sizeof(atqa);
  const MFRC522::StatusCode status = rfid.PICC_WakeupA(atqa, &atqaSize);
  if (status == MFRC522::STATUS_OK || status == MFRC522::STATUS_COLLISION) {
    rfid.PICC_HaltA();
    return true;
  }
  return false;
}

void pollCard() {
  if (!cardArmed) {
    if (cardStillOnReader()) {
      absenceTiming = false;
    } else if (!absenceTiming) {
      absenceTiming = true;
      absentSinceMs = millis();
    } else if (millis() - absentSinceMs >= kCardRemovalMs) {
      cardArmed = true;
      absenceTiming = false;
      if (!pendingOperation) showMessage("Ready", "Scan RFID card");
    }
    return;
  }

  if (!rfid.PICC_IsNewCardPresent() || !rfid.PICC_ReadCardSerial()) return;
  scanReceivedAtMs = millis();
  cardArmed = false;
  absenceTiming = false;
  const String uid = normalizedUid(rfid.uid);
  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();
  if (pendingOperation) {
    showMessage("Request pending", "Wait for server", "Then remove card");
    return;
  }
  if (rfid.uid.size != 4 && rfid.uid.size != 7 && rfid.uid.size != 10) {
    showMessage("Malformed RFID", "Card UID length invalid");
    return;
  }
  emitMetric("rfid_read", nullptr, true, true);
  if (WiFi.status() != WL_CONNECTED) {
    setUnknownLeds();
    showMessage("Wi-Fi unavailable", "Gate remains closed");
    return;
  }
  showMessage("RFID detected", "Checking session...");
  bool parked = false;
  if (!statusForUid(uid, parked)) {
    setUnknownLeds();
    showMessage("Server unavailable", "Gate remains closed");
    return;
  }
  if (!beginOperation(uid, parked ? "exit" : "entry")) {
    showMessage("Storage error", "Request not sent", "Gate remains closed");
    return;
  }
  if (parked) showMessage("Exit request", "Confirming session", "Gate remains closed");
  else showMessage("Entry request", "Allocating a slot", "Gate remains closed");
}

void updateWifi() {
  const bool connected = WiFi.status() == WL_CONNECTED;
  if (connected && !wifiWasConnected) {
    wifiWasConnected = true;
    emitMetric("wifi_connected", nullptr, false, false,
               wifiDisconnectedAtMs ? millis() - wifiDisconnectedAtMs : 0);
    wifiDisconnectedAtMs = 0;
  } else if (!connected && wifiWasConnected) {
    wifiWasConnected = false;
    wifiDisconnectedAtMs = millis();
    emitMetric("wifi_disconnected");
  }
  if (WIFI_SSID[0] == '\0' || connected) return;
  setUnknownLeds();
  if (!wifiStarted) {
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    wifiStarted = true;
    showMessage("Connecting Wi-Fi...");
    lastWifiAttemptMs = millis();
  } else if (millis() - lastWifiAttemptMs >= kWifiRetryMs) {
    WiFi.reconnect();
    lastWifiAttemptMs = millis();
    showMessage("Reconnecting Wi-Fi");
  }
}

void updateGate() {
  if (gateOpen && static_cast<int32_t>(millis() - gateCloseAtMs) >= 0) {
    gateServo.write(SERVO_CLOSED_DEGREES);
    emitMetric("gate_command", pendingType.c_str(), false, false,
               millis() - scanReceivedAtMs);
    gateOpen = false;
    if (pendingOperation) {
      telemetryMask |= 4;
      preferences.putUChar("telemetry", telemetryMask);
    }
    showMessage("Gate closed", "Ready for next vehicle");
  }
}
}  // namespace

void setup() {
  Serial.begin(115200);
  for (uint8_t pin : Pins::SlotLeds) {
    digitalWrite(pin, LOW);
    pinMode(pin, OUTPUT);
  }
  refreshLeds();  // Blinking means availability is unknown until a status fetch succeeds.

  Wire.begin(Pins::I2cSda, Pins::I2cScl);
  displayReady = display.begin(SSD1306_SWITCHCAPVCC, Pins::OledAddress);
  showMessage("Initializing RFID");

  SPI.begin(Pins::RfidSck, Pins::RfidMiso, Pins::RfidMosi, Pins::RfidSs);
  rfid.PCD_Init();
  const byte readerVersion = rfid.PCD_ReadRegister(MFRC522::VersionReg);
  pinMode(Pins::RfidSs, OUTPUT);
  digitalWrite(Pins::RfidSs, HIGH);
  const byte lowClockVersion = readRfidVersionAtLowClock();
  pinMode(Pins::RfidMiso, INPUT_PULLUP);
  const bool misoIdleHigh = digitalRead(Pins::RfidMiso) == HIGH;
  const bool resetPinHigh = digitalRead(Pins::RfidReset) == HIGH;
  JsonDocument readerMetric;
  readerMetric["event"] = "rfid_reader";
  readerMetric["uptime_ms"] = millis();
  readerMetric["version_register"] = readerVersion;
  readerMetric["low_clock_version_register"] = lowClockVersion;
  readerMetric["reset_pin_high"] = resetPinHigh;
  readerMetric["miso_idle_high"] = misoIdleHigh;
  readerMetric["ready"] = readerVersion != 0x00 && readerVersion != 0xFF;
  readerMetric["free_heap_bytes"] = ESP.getFreeHeap();
  serializeJson(readerMetric, Serial);
  Serial.println();
  gateServo.setPeriodHertz(50);
  gateReady = gateServo.attach(Pins::GateServo, 500, 2400) >= 0;
  if (gateReady) gateServo.write(SERVO_CLOSED_DEGREES);
  else showMessage("Gate unavailable", "Gate remains closed");

  storageReady = preferences.begin("parking", false);
  emitMetric("controller_boot");
  if (!storageReady) showMessage("Storage unavailable", "RFID requests disabled");
  pendingOperation = storageReady && preferences.getBool("pending", false);
  if (pendingOperation) {
    pendingUid = preferences.getString("uid", "");
    pendingKey = preferences.getString("key", "");
    pendingType = preferences.getString("type", "");
    scanReceivedAtMs = millis();
    pendingGateDone = preferences.getBool("gate_done", false);
    telemetryMask = preferences.getUChar("telemetry", 0);
    telemetryAck = preferences.getUChar("telemetry_ack", 0);
    if (pendingGateDone) {
      telemetryMask |= 4;
      preferences.putUChar("telemetry", telemetryMask);
    }
    if (!pendingUid.length() || !pendingKey.length() ||
        (pendingType != "entry" && pendingType != "exit")) clearPending();
    else showMessage("Recovering request", "Using saved idempotency key");
  } else if (WIFI_SSID[0] == '\0') {
    showMessage("Wi-Fi not configured", "Copy local_config", "and restart");
  } else {
    showMessage("System initialized", "Connecting Wi-Fi...");
  }
  updateWifi();
}

void loop() {
  updateWifi();
  updateGate();
  refreshLeds();

  if (WiFi.status() == WL_CONNECTED) {
    flushTelemetry();
    if (millis() - lastStatusMs >= STATUS_POLL_MILLISECONDS) {
      lastStatusMs = millis();
      SlotState latest;
      if (checkHealth() && fetchStatus(latest)) {
        slotState = latest;
        refreshLeds();
        if (!pendingOperation && !gateOpen) showMessage("Ready", "Scan RFID card");
      } else {
        setUnknownLeds();
        showMessage("Backend status error", "Slot state unknown");
      }
    }
    processPendingOperation();
    if (!pendingOperation && !gateOpen) pollCard();
  }
  delay(5);
}
