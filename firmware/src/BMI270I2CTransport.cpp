#include "BMI270I2CTransport.h"

#include <Arduino.h>
#include <Wire.h>

#include <bmi270.h>

#include "I2CManager.h"
#include "esp_timer.h"

namespace {

constexpr BMI2_INTF_RETURN_TYPE kTransportFailure = BMI2_E_COM_FAIL;

} // namespace

BMI270I2CTransport::BMI270I2CTransport(uint8_t busIndex, uint8_t address) {
  configure(busIndex, address);
}

void BMI270I2CTransport::configure(uint8_t busIndex, uint8_t address) {
  busIndex_ = busIndex;
  address_ = address;
}

void BMI270I2CTransport::attach(struct bmi2_dev& device) {
  device.intf = BMI2_I2C_INTF;
  device.intf_ptr = this;
  device.read = &BMI270I2CTransport::readCallback;
  device.write = &BMI270I2CTransport::writeCallback;
  device.delay_us = &BMI270I2CTransport::delayUsCallback;
  device.read_write_len = 32;
  device.config_file_ptr = nullptr;
}

bool BMI270I2CTransport::probeChipId(uint8_t& chipId) {
  chipId = 0;
  return read_(BMI2_CHIP_ID_ADDR, &chipId, 1) == BMI2_INTF_RET_SUCCESS;
}

void BMI270I2CTransport::resetDiagnostics() {
  diagnostics_ = BMI270I2CTransportDiagnostics{};
  lastReadTiming_ = BMI270I2CReadTiming{};
}

bool BMI270I2CTransport::beginTransaction(
    uint8_t registerAddress,
    uint16_t expectedBytes) {
  if (transactionWire_) {
    recordFailure_(
        BMI270I2CFailureStage::InvalidArgument,
        kTransportFailure,
        registerAddress,
        expectedBytes,
        0);
    return false;
  }
  TwoWire* wire = I2CManager::bus(busIndex_);
  if (!wire) {
    recordFailure_(
        BMI270I2CFailureStage::BusUnavailable,
        kTransportFailure,
        registerAddress,
        expectedBytes,
        0);
    return false;
  }
  if (!acquireLock_(wire, registerAddress, expectedBytes)) return false;
  transactionWire_ = wire;
  return true;
}

void BMI270I2CTransport::endTransaction() {
  if (!transactionWire_) return;
  I2CManager::unlock(transactionWire_);
  transactionWire_ = nullptr;
}

BMI2_INTF_RETURN_TYPE BMI270I2CTransport::readCallback(
    uint8_t registerAddress,
    uint8_t* data,
    uint32_t length,
    void* context) {
  if (!context) return kTransportFailure;
  return static_cast<BMI270I2CTransport*>(context)->read_(registerAddress, data, length);
}

BMI2_INTF_RETURN_TYPE BMI270I2CTransport::writeCallback(
    uint8_t registerAddress,
    const uint8_t* data,
    uint32_t length,
    void* context) {
  if (!context) return kTransportFailure;
  return static_cast<BMI270I2CTransport*>(context)->write_(registerAddress, data, length);
}

void BMI270I2CTransport::delayUsCallback(uint32_t periodUs, void* context) {
  (void)context;
  if (periodUs >= 1000) {
    delay(periodUs / 1000);
    periodUs %= 1000;
  }
  if (periodUs) delayMicroseconds(periodUs);
}

BMI2_INTF_RETURN_TYPE BMI270I2CTransport::read_(
    uint8_t registerAddress,
    uint8_t* data,
    uint32_t length) {
  if ((!data && length) || length > kMaximumReadBytes) {
    return recordFailure_(
        BMI270I2CFailureStage::InvalidArgument,
        kTransportFailure,
        registerAddress,
        static_cast<uint16_t>(length > UINT16_MAX ? UINT16_MAX : length),
        0);
  }
  if (length == 0) {
    recordSuccess_();
    return BMI2_INTF_RET_SUCCESS;
  }

  lastReadTiming_ = BMI270I2CReadTiming{};
  TwoWire* wire = transactionWire_ ? transactionWire_ : I2CManager::bus(busIndex_);
  if (!wire) {
    return recordFailure_(
        BMI270I2CFailureStage::BusUnavailable,
        kTransportFailure,
        registerAddress,
        static_cast<uint16_t>(length),
        0);
  }
  const bool locallyLocked = transactionWire_ == nullptr;
  if (locallyLocked &&
      !acquireLock_(wire, registerAddress, static_cast<uint16_t>(length))) {
    return kTransportFailure;
  }

  const uint64_t transferStartUs = static_cast<uint64_t>(esp_timer_get_time());

  wire->beginTransmission(address_);
  if (wire->write(registerAddress) != 1) {
    const uint8_t result = wire->endTransmission(true);
    if (locallyLocked) I2CManager::unlock(wire);
    return recordFailure_(
        BMI270I2CFailureStage::RegisterAddress,
        result,
        registerAddress,
        1,
        0);
  }

  const uint8_t transmitResult = wire->endTransmission(false);
  if (transmitResult != 0) {
    if (locallyLocked) I2CManager::unlock(wire);
    return recordFailure_(
        BMI270I2CFailureStage::EndTransmission,
        transmitResult,
        registerAddress,
        static_cast<uint16_t>(length),
        0);
  }

  const size_t received = wire->requestFrom(
      static_cast<uint16_t>(address_),
      static_cast<size_t>(length),
      true);
  if (received != length) {
    while (wire->available()) (void)wire->read();
    if (locallyLocked) I2CManager::unlock(wire);
    return recordFailure_(
        BMI270I2CFailureStage::RequestBytes,
        kTransportFailure,
        registerAddress,
        static_cast<uint16_t>(length),
        static_cast<uint16_t>(received));
  }

  uint32_t copied = 0;
  while (copied < length && wire->available()) {
    const int value = wire->read();
    if (value < 0) break;
    data[copied++] = static_cast<uint8_t>(value);
  }
  const uint64_t transferEndUs = static_cast<uint64_t>(esp_timer_get_time());
  if (locallyLocked) I2CManager::unlock(wire);

  if (copied != length) {
    return recordFailure_(
        BMI270I2CFailureStage::ReadBytes,
        kTransportFailure,
        registerAddress,
        static_cast<uint16_t>(length),
        static_cast<uint16_t>(copied));
  }

  lastReadTiming_.transferStartUs = transferStartUs;
  lastReadTiming_.transferEndUs = transferEndUs;
  lastReadTiming_.bytes = length;
  lastReadTiming_.registerAddress = registerAddress;
  lastReadTiming_.valid = true;
  recordSuccess_();
  return BMI2_INTF_RET_SUCCESS;
}

BMI2_INTF_RETURN_TYPE BMI270I2CTransport::write_(
    uint8_t registerAddress,
    const uint8_t* data,
    uint32_t length) {
  if ((!data && length) || length > kMaximumWriteBytes) {
    return recordFailure_(
        BMI270I2CFailureStage::InvalidArgument,
        kTransportFailure,
        registerAddress,
        static_cast<uint16_t>(length > UINT16_MAX ? UINT16_MAX : length),
        0);
  }

  TwoWire* wire = transactionWire_ ? transactionWire_ : I2CManager::bus(busIndex_);
  if (!wire) {
    return recordFailure_(
        BMI270I2CFailureStage::BusUnavailable,
        kTransportFailure,
        registerAddress,
        static_cast<uint16_t>(length),
        0);
  }
  const bool locallyLocked = transactionWire_ == nullptr;
  if (locallyLocked &&
      !acquireLock_(wire, registerAddress, static_cast<uint16_t>(length))) {
    return kTransportFailure;
  }

  wire->beginTransmission(address_);
  if (wire->write(registerAddress) != 1) {
    const uint8_t result = wire->endTransmission(true);
    if (locallyLocked) I2CManager::unlock(wire);
    return recordFailure_(
        BMI270I2CFailureStage::RegisterAddress,
        result,
        registerAddress,
        1,
        0);
  }

  const size_t written = length ? wire->write(data, static_cast<size_t>(length)) : 0;
  if (written != length) {
    const uint8_t result = wire->endTransmission(true);
    if (locallyLocked) I2CManager::unlock(wire);
    return recordFailure_(
        BMI270I2CFailureStage::WritePayload,
        result,
        registerAddress,
        static_cast<uint16_t>(length),
        static_cast<uint16_t>(written));
  }

  const uint8_t result = wire->endTransmission(true);
  if (locallyLocked) I2CManager::unlock(wire);
  if (result != 0) {
    return recordFailure_(
        BMI270I2CFailureStage::EndTransmission,
        result,
        registerAddress,
        static_cast<uint16_t>(length),
        static_cast<uint16_t>(written));
  }

  recordSuccess_();
  return BMI2_INTF_RET_SUCCESS;
}

bool BMI270I2CTransport::acquireLock_(
    TwoWire* wire,
    uint8_t registerAddress,
    uint16_t expectedBytes) {
  ++diagnostics_.busLockAttempts;
  const uint64_t waitStartUs = static_cast<uint64_t>(esp_timer_get_time());
  const bool locked = I2CManager::lock(wire, kLockTimeoutMs);
  const uint64_t waited64 =
      static_cast<uint64_t>(esp_timer_get_time()) - waitStartUs;
  const uint32_t waitedUs = waited64 > UINT32_MAX
      ? UINT32_MAX
      : static_cast<uint32_t>(waited64);
  diagnostics_.busLockWaitTotalUs += waitedUs;
  if (waitedUs > diagnostics_.busLockWaitMaximumUs) {
    diagnostics_.busLockWaitMaximumUs = waitedUs;
  }
  if (locked) {
    const board::I2CProfile* busProfile = I2CManager::profile(busIndex_);
    if (busProfile && busProfile->hz) wire->setClock(busProfile->hz);
    return true;
  }
  ++diagnostics_.busLockTimeouts;
  recordFailure_(
      BMI270I2CFailureStage::BusLockTimeout,
      kTransportFailure,
      registerAddress,
      expectedBytes,
      0);
  return false;
}

void BMI270I2CTransport::recordSuccess_() {
  ++diagnostics_.operations;
  if (diagnostics_.failureStreak) ++diagnostics_.recoveries;
  diagnostics_.failureStreak = 0;
  diagnostics_.lastOperationOk = true;
}

BMI2_INTF_RETURN_TYPE BMI270I2CTransport::recordFailure_(
    BMI270I2CFailureStage stage,
    int16_t resultCode,
    uint8_t registerAddress,
    uint16_t expectedBytes,
    uint16_t receivedBytes) {
  ++diagnostics_.operations;
  ++diagnostics_.failures;
  const size_t stageIndex = static_cast<size_t>(stage);
  if (stageIndex < BMI270I2CTransportDiagnostics::kFailureStageCount) {
    ++diagnostics_.failuresByStage[stageIndex];
  }
  ++diagnostics_.failureStreak;
  if (diagnostics_.failureStreak > diagnostics_.maximumFailureStreak) {
    diagnostics_.maximumFailureStreak = diagnostics_.failureStreak;
  }
  diagnostics_.lastOperationOk = false;
  diagnostics_.lastFailure.stage = stage;
  diagnostics_.lastFailure.resultCode = resultCode;
  diagnostics_.lastFailure.registerAddress = registerAddress;
  diagnostics_.lastFailure.expectedBytes = expectedBytes;
  diagnostics_.lastFailure.receivedBytes = receivedBytes;
  return kTransportFailure;
}
