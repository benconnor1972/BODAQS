#pragma once

#include <stddef.h>
#include <stdint.h>

#include <bmi2_defs.h>

struct bmi2_dev;
class TwoWire;

enum class BMI270I2CFailureStage : uint8_t {
  None = 0,
  InvalidArgument,
  BusUnavailable,
  BusLockTimeout,
  RegisterAddress,
  WritePayload,
  EndTransmission,
  RequestBytes,
  ReadBytes,
};

struct BMI270I2CFailure {
  BMI270I2CFailureStage stage = BMI270I2CFailureStage::None;
  int16_t resultCode = 0;
  uint8_t registerAddress = 0;
  uint16_t expectedBytes = 0;
  uint16_t receivedBytes = 0;
};

struct BMI270I2CTransportDiagnostics {
  static constexpr size_t kFailureStageCount = 9;
  uint32_t operations = 0;
  uint32_t failures = 0;
  uint32_t recoveries = 0;
  uint32_t failureStreak = 0;
  uint32_t maximumFailureStreak = 0;
  uint32_t busLockAttempts = 0;
  uint32_t busLockTimeouts = 0;
  uint64_t busLockWaitTotalUs = 0;
  uint32_t busLockWaitMaximumUs = 0;
  bool lastOperationOk = false;
  BMI270I2CFailure lastFailure;
  uint32_t failuresByStage[kFailureStageCount] {};
};

struct BMI270I2CReadTiming {
  uint64_t transferStartUs = 0;
  uint64_t transferEndUs = 0;
  uint32_t bytes = 0;
  uint8_t registerAddress = 0;
  bool valid = false;
};

class BMI270I2CTransport {
public:
  static constexpr uint32_t kLockTimeoutMs = 50;
  static constexpr uint32_t kMaximumReadBytes = 2304;
  static constexpr uint32_t kMaximumWriteBytes = 127;

  BMI270I2CTransport() = default;
  BMI270I2CTransport(uint8_t busIndex, uint8_t address);

  void configure(uint8_t busIndex, uint8_t address);
  void attach(struct bmi2_dev& device);
  bool probeChipId(uint8_t& chipId);

  uint8_t busIndex() const { return busIndex_; }
  uint8_t address() const { return address_; }
  const BMI270I2CTransportDiagnostics& diagnostics() const { return diagnostics_; }
  const BMI270I2CReadTiming& lastReadTiming() const { return lastReadTiming_; }
  void resetDiagnostics();
  bool beginTransaction(uint8_t registerAddress, uint16_t expectedBytes);
  void endTransaction();

  static BMI2_INTF_RETURN_TYPE readCallback(
      uint8_t registerAddress,
      uint8_t* data,
      uint32_t length,
      void* context);
  static BMI2_INTF_RETURN_TYPE writeCallback(
      uint8_t registerAddress,
      const uint8_t* data,
      uint32_t length,
      void* context);
  static void delayUsCallback(uint32_t periodUs, void* context);

private:
  BMI2_INTF_RETURN_TYPE read_(
      uint8_t registerAddress,
      uint8_t* data,
      uint32_t length);
  BMI2_INTF_RETURN_TYPE write_(
      uint8_t registerAddress,
      const uint8_t* data,
      uint32_t length);
  void recordSuccess_();
  bool acquireLock_(
      TwoWire* wire,
      uint8_t registerAddress,
      uint16_t expectedBytes);
  BMI2_INTF_RETURN_TYPE recordFailure_(
      BMI270I2CFailureStage stage,
      int16_t resultCode,
      uint8_t registerAddress,
      uint16_t expectedBytes,
      uint16_t receivedBytes);

  uint8_t busIndex_ = 0;
  uint8_t address_ = 0;
  BMI270I2CTransportDiagnostics diagnostics_;
  BMI270I2CReadTiming lastReadTiming_;
  TwoWire* transactionWire_ = nullptr;
};
