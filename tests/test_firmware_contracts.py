from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = (ROOT / "firmware/esp32_controller/src/main.cpp").read_text(encoding="utf-8")


def function_body(name: str, following: str) -> str:
    start = CONTROLLER.index(name)
    end = CONTROLLER.index(following, start)
    return CONTROLLER[start:end]


def test_gate_nvs_flag_is_persisted_before_servo_command() -> None:
    body = function_body("bool openGateOnce()", "void flushTelemetry()")

    assert "if (pendingGateDone) return true;" in body
    assert body.index('preferences.putBool("gate_done", true)') < body.index(
        "gateServo.write(SERVO_OPEN_DEGREES)"
    )


def test_lifecycle_response_is_validated_and_committed_before_gate_call() -> None:
    body = function_body("void processPendingOperation()", "bool cardStillOnReader()")

    assert body.index("deserializeJson(result, response.body)") < body.index(
        "verifyEntryCommit(pendingUid, slotId)"
    )
    assert body.index("verifyEntryCommit(pendingUid, slotId)") < body.index("openGateOnce()")
    assert body.index("verifyExitCommit(pendingUid)") < body.index("openGateOnce()")
    assert 'String(result["gate_action"] | "") != "open"' in body
    assert 'showMessage("Invalid server reply", "Gate remains closed"' in body


def test_pending_key_is_persisted_before_lifecycle_request_and_reused() -> None:
    begin = function_body("bool beginOperation(", "bool verifyEntryCommit(")
    process = function_body("void processPendingOperation()", "bool cardStillOnReader()")

    assert begin.index("pendingKey = newIdempotencyKey()") < begin.index("persistPending()")
    assert process.index('request["idempotency_key"] = pendingKey') < process.index(
        "requestHttp(backendUrl(path), \"POST\", encoded)"
    )
    assert "preferences.getString(\"key\", \"\")" in CONTROLLER


def test_wifi_loss_sets_occupancy_unknown_and_held_card_is_suppressed() -> None:
    wifi = function_body("void updateWifi()", "void updateGate()")
    poll = function_body("void pollCard()", "void updateWifi()")

    assert "setUnknownLeds();" in wifi
    assert "WiFi.reconnect();" in wifi
    assert "if (!cardArmed)" in poll
    assert "kCardRemovalMs" in poll


def test_controller_serial_messages_do_not_print_rfid_or_wifi_secrets() -> None:
    assert "Serial.println(title)" in CONTROLLER
    assert "Serial.println(pendingUid)" not in CONTROLLER
    assert "Serial.print(pendingUid)" not in CONTROLLER
    assert "Serial.println(WIFI_PASSWORD)" not in CONTROLLER


def test_controller_adds_bearer_token_without_logging_it() -> None:
    body = function_body("HttpResult requestHttp(", "bool checkHealth()")

    assert "DEVICE_API_TOKEN[0] != '\\0'" in body
    assert 'http.addHeader("Authorization", String("Bearer ") + DEVICE_API_TOKEN)' in body
    assert "Serial.println(DEVICE_API_TOKEN)" not in CONTROLLER


def test_controller_reports_rc522_spi_presence_at_boot() -> None:
    setup = function_body("void setup()", "void loop()")
    low_clock_read = function_body("byte readRfidVersionAtLowClock()", "HttpResult requestHttp(")
    bit_bang_read = function_body(
        "byte readRfidVersionBitBanged()", "byte readRfidVersionAtLowClock()"
    )
    bit_bang_transfer = function_body(
        "byte transferRfidByteBitBanged(byte value)", "byte readRfidVersionBitBanged()"
    )

    assert "rfid.PCD_ReadRegister(MFRC522::VersionReg)" in setup
    assert "readRfidVersionAtLowClock()" in setup
    assert "readRfidVersionBitBanged()" in setup
    assert "digitalRead(Pins::RfidMiso)" in bit_bang_transfer
    assert "digitalWrite(Pins::RfidSs, LOW)" in bit_bang_read
    assert 'readerMetric["bit_banged_version_register"] = bitBangVersion' in setup
    assert "SPI.transfer(0x80 | MFRC522::VersionReg)" in low_clock_read
    assert "VersionReg << 1" not in low_clock_read
    assert 'readerMetric["event"] = "rfid_reader"' in setup
    assert 'readerMetric["version_register"] = readerVersion' in setup
    assert 'readerMetric["ready"] = readerVersion != 0x00 && readerVersion != 0xFF' in setup
    assert 'readerMetric["low_clock_version_register"] = lowClockVersion' in setup
    assert 'const bool resetPinHigh = digitalRead(Pins::RfidReset) == HIGH' in setup
    assert 'readerMetric["reset_pin_high"] = resetPinHigh' in setup
    assert 'readerMetric["miso_idle_high"] = misoIdleHigh' in setup
