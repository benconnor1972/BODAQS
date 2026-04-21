#pragma once

#include "AS5600StringPotSensorBase.h"
#include "SensorTypes.h"

class TwoWire;

class AS5600StringPotI2C : public AS5600StringPotSensorBase {
public:
  struct Params : public BaseParams {
    uint8_t  busIndex = 0;
    uint8_t  i2cAddr = 0x36;
  };

  explicit AS5600StringPotI2C(const Params& p);

  void begin() override;
  bool reconfigureFromSpec(const SensorSpec& spec) override;

  static const ParamDef* paramDefs(size_t& count);
  static Sensor* create(const char* instanceName, const ParamPack& params, bool mutedDefault);

protected:
  int readWrappedCountsOnce() const override;

private:
  bool probe_() const;
  bool readReg16_(uint8_t reg, uint16_t& value) const;
  bool readWrappedCounts_(int& wrapped) const;

private:
  uint8_t  m_busIndex = 0;
  uint8_t  m_i2cAddr = 0x36;
  mutable TwoWire* m_wire = nullptr;
  mutable bool m_warnedNoBus = false;
  mutable bool m_warnedRead = false;
  mutable int  m_lastGoodWrapped = 0;
  mutable bool m_haveLastGoodWrapped = false;
};
