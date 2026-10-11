#if defined(BODAQS_BMI270_I2C_PROBE)

#include "BMI270I2CProbe.h"

#include <Arduino.h>
#include "ConfigManager.h"
#include "I2CBusScheduler.h"
#include "I2CManager.h"
#include "esp32-hal-i2c.h"
#include "esp_system.h"

namespace {
constexpr uint16_t kReadsPerPhase = 1000;
constexpr uint32_t kGapMs = 5;
constexpr uint32_t kRates[] = {400000, 100000, 400000};
constexpr uint8_t kChipIdRegister = 0x00;
constexpr uint8_t kExpectedChipId = 0x24;

struct Target {
  uint8_t bus;
  uint8_t address;
  char name[16];
};

struct Results {
  uint32_t correct = 0;
  uint32_t wrong = 0;
  uint32_t transferFailed = 0;
  uint32_t timeouts = 0;
  uint32_t shortReads = 0;
  uint32_t badRun = 0;
  uint32_t maximumBadRun = 0;
  uint32_t wrongValues[256] = {};
};

void testTarget(const Target& target, uint8_t phase, uint32_t hz) {
  TwoWire* wire = I2CManager::bus(target.bus);
  if (!wire || !I2CManager::lock(wire, 200)) {
    Serial.printf("[IMU-PROBE] SKIPPED phase=%u bus=%u addr=0x%02X unavailable_or_busy\n",
                  phase, target.bus, target.address);
    return;
  }

  const uint32_t savedHz = wire->getClock();
  if (!savedHz || !wire->setClock(hz)) {
    Serial.printf("[IMU-PROBE] ABORTED phase=%u bus=%u addr=0x%02X clock_setup_failed\n",
                  phase, target.bus, target.address);
    I2CManager::unlock(wire);
    return;
  }

  const uint16_t timeoutMs = wire->getTimeOut();
  Serial.printf("[IMU-PROBE] begin phase=%u sensor=%s bus=%u addr=0x%02X hz=%lu reads=%u timeout_ms=%u uptime_ms=%lu\n",
                phase, target.name, target.bus, target.address,
                (unsigned long)wire->getClock(), kReadsPerPhase, timeoutMs,
                (unsigned long)millis());

  Results results;
  uint8_t examples = 0;
  const uint32_t startedMs = millis();
  for (uint16_t attempt = 1; attempt <= kReadsPerPhase; ++attempt) {
    uint8_t value = 0;
    size_t received = 0;
    // Same HAL call used by Wire.requestFrom() for the production repeated-
    // START read. Calling it directly preserves its ESP error code and avoids
    // printing a Wire error for every failed read. The manager mutex prevents
    // other bus users from restoring 400 kHz in the middle of this block.
    const esp_err_t error = i2cWriteReadNonStop(
        target.bus, target.address, &kChipIdRegister, 1, &value, 1,
        timeoutMs, &received);
    bool correct = false;
    if (error != ESP_OK) {
      ++results.transferFailed;
      if (error == ESP_ERR_TIMEOUT) ++results.timeouts;
    } else if (received != 1) {
      ++results.shortReads;
    } else if (value != kExpectedChipId) {
      ++results.wrong;
      ++results.wrongValues[value];
    } else {
      ++results.correct;
      correct = true;
    }

    if (correct) {
      results.badRun = 0;
    } else {
      ++results.badRun;
      if (results.badRun > results.maximumBadRun) {
        results.maximumBadRun = results.badRun;
      }
      if (examples < 8) {
        ++examples;
        if (error == ESP_OK && received == 1) {
          Serial.printf("[IMU-PROBE] wrong phase=%u bus=%u addr=0x%02X attempt=%u value=0x%02X expected=0x24\n",
                        phase, target.bus, target.address, attempt, value);
        } else {
          Serial.printf("[IMU-PROBE] transfer_error phase=%u bus=%u addr=0x%02X attempt=%u esp=%d(%s) received=%u\n",
                        phase, target.bus, target.address, attempt, (int)error,
                        esp_err_to_name(error), (unsigned)received);
        }
      }
    }

    if (attempt % 100 == 0) {
      Serial.printf("[IMU-PROBE] progress phase=%u bus=%u addr=0x%02X reads=%u correct=%lu wrong=%lu transfer_failed=%lu short_read=%lu\n",
                    phase, target.bus, target.address, attempt,
                    (unsigned long)results.correct, (unsigned long)results.wrong,
                    (unsigned long)results.transferFailed, (unsigned long)results.shortReads);
    }
    delay(kGapMs); // Feed the idle task/watchdog even on an all-error block.
  }

  const bool restored = wire->setClock(savedHz);
  I2CManager::unlock(wire);
  Serial.printf("[IMU-PROBE] summary phase=%u bus=%u addr=0x%02X hz=%lu reads=%u correct=%lu wrong=%lu transfer_failed=%lu timeout=%lu short_read=%lu max_bad_run=%lu elapsed_ms=%lu restored_hz=%lu restore_ok=%u\n",
                phase, target.bus, target.address, (unsigned long)hz, kReadsPerPhase,
                (unsigned long)results.correct, (unsigned long)results.wrong,
                (unsigned long)results.transferFailed, (unsigned long)results.timeouts,
                (unsigned long)results.shortReads, (unsigned long)results.maximumBadRun,
                (unsigned long)(millis() - startedMs), (unsigned long)savedHz, restored);
  for (uint16_t value = 0; value < 256; ++value) {
    if (!results.wrongValues[value]) continue;
    Serial.printf("[IMU-PROBE] wrong_value phase=%u bus=%u addr=0x%02X value=0x%02X count=%lu\n",
                  phase, target.bus, target.address, value,
                  (unsigned long)results.wrongValues[value]);
  }
}
} // namespace

void BMI270I2CProbe::run(const LoggerConfig& config) {
  Serial.printf("[IMU-PROBE] START reset_reason=%u phases=400000,100000,400000 reads_per_device_per_phase=%u gap_ms=%lu\n",
                (unsigned)esp_reset_reason(), kReadsPerPhase, (unsigned long)kGapMs);
  Serial.println("[IMU-PROBE] CHIP_ID only; no sensor reset, reinitialization, power cycle or bus recovery between phases");
  // At the end of setup the logger/scheduler have not started acquisition.
  // Refuse to interfere with a session if this hook is moved in future.
  if (I2CBusScheduler::isRunning()) {
    Serial.println("[IMU-PROBE] ABORTED acquisition_scheduler_running");
    return;
  }

  Target targets[MAX_SENSORS] = {};
  uint8_t count = 0;
  for (uint8_t index = 0; index < config.sensorCount(); ++index) {
    SensorSpec spec;
    if (!config.getSensorSpec(index, spec) || spec.type != SensorType::BMI270ImuI2C) continue;
    // Match BMI270ImuSensor's default bus/address; include muted and failed
    // sensors rather than selecting only the ones which initialized.
    long bus = 1;
    long address = 0x68;
    spec.params.getInt("i2c_bus", bus);
    spec.params.getInt("i2c_addr", address);
    if (bus < 0 || bus >= board::BOARD_MAX_I2C_BUSES ||
        (address != 0x68 && address != 0x69)) {
      Serial.printf("[IMU-PROBE] SKIPPED sensor=%s invalid_bus_or_address\n", spec.name);
      continue;
    }
    bool duplicate = false;
    for (uint8_t previous = 0; previous < count; ++previous) {
      if (targets[previous].bus == bus && targets[previous].address == address) duplicate = true;
    }
    if (duplicate) continue;
    Target& target = targets[count++];
    target.bus = static_cast<uint8_t>(bus);
    target.address = static_cast<uint8_t>(address);
    snprintf(target.name, sizeof(target.name), "%s", spec.name);
  }

  for (uint8_t phase = 0; phase < 3; ++phase) {
    for (uint8_t index = 0; index < count; ++index) {
      testTarget(targets[index], phase + 1, kRates[phase]);
    }
  }
  Serial.printf("[IMU-PROBE] DONE devices=%u normal_loop_resuming\n", count);
}

#endif // BODAQS_BMI270_I2C_PROBE
