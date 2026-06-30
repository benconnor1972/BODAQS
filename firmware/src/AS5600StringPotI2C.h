#pragma once

#include "AS5600StringPotSensorBase.h"
#include "I2CBusScheduler.h"
#include "SensorTypes.h"

class TwoWire;

class AS5600StringPotI2C : public AS5600StringPotSensorBase, public I2CAsyncClient {
public:
  struct Params : public BaseParams {
    uint8_t  busIndex = 0;
    uint8_t  i2cAddr = 0x36;
    uint16_t asyncRateHz = 0; // 0 = follow logger sample rate
  };

  explicit AS5600StringPotI2C(const Params& p);

  void begin() override;
  void onLoggingStart() override;
  void onLoggingStop() override;
  SensorSampleMode sampleMode() const override { return SensorSampleMode::Asynchronous; }
  bool reconfigureFromSpec(const SensorSpec& spec) override;

  const char* asyncClientName() const override { return name(); }
  const char* asyncClientKind() const override { return "as5600_string_pot_i2c"; }
  uint8_t asyncI2CBusIndex() const override { return m_busIndex; }
  uint8_t asyncI2CAddress() const override { return m_i2cAddr; }
  uint16_t asyncTargetRateHz() const override;
  bool asyncMuted() const override { return muted(); }
  bool asyncAcquire() override;

  static const ParamDef* paramDefs(size_t& count);
  static Sensor* create(const char* instanceName, const ParamPack& params, bool mutedDefault);

protected:
  int readWrappedCountsOnce() const override;

private:
  struct AsyncSnapshot {
    bool have = false;
    bool readOk = false;
    bool reused = false;
    int wrapped = 0;
    uint32_t readFailures = 0;
    uint32_t seq = 0;
    uint64_t acquiredUs = 0;
  };

  bool probe_() const;
  bool readReg16_(uint8_t reg, uint16_t& value) const;
  bool readWrappedCounts_(int& wrapped) const;
  bool readWrappedCountsDirectOnce_(int& wrapped) const;
  bool acquireAsyncSample_() const;
  void resetAsyncSnapshot_() const;
  void publishAsyncSnapshot_(const AsyncSnapshot& snapshot) const;
  bool copyAsyncSnapshot_(AsyncSnapshot& snapshot) const;

private:
  uint8_t  m_busIndex = 0;
  uint8_t  m_i2cAddr = 0x36;
  uint16_t m_asyncRateHz = 0;
  mutable TwoWire* m_wire = nullptr;
  mutable bool m_warnedNoBus = false;
  mutable bool m_warnedRead = false;
  mutable int  m_lastGoodWrapped = 0;
  mutable bool m_haveLastGoodWrapped = false;
  mutable bool m_lastReadOk = false;
  mutable bool m_lastReadReused = false;
  mutable uint32_t m_readFailures = 0;
  mutable uint32_t m_nextReadAttemptMs = 0;
  mutable bool m_asyncLoggingActive = false;
  mutable uint32_t m_asyncNextSeq = 0;
  mutable uint32_t m_asyncLastLoggedSeq = 0;
  mutable AsyncSnapshot m_asyncSnapshot;
#if defined(ESP32)
  mutable portMUX_TYPE m_asyncMux = portMUX_INITIALIZER_UNLOCKED;
#endif
};
