#pragma once

#include "AS5600StringPotSensorBase.h"
#include "SensorTypes.h"

class AS5600StringPotAnalog : public AS5600StringPotSensorBase {
public:
  struct Params : public BaseParams {
    uint8_t pin = uint8_t(-1);
  };

  explicit AS5600StringPotAnalog(const Params& p);

  void begin() override;

  static const ParamDef* paramDefs(size_t& count);
  static Sensor* create(const char* instanceName, const ParamPack& params, bool mutedDefault);

protected:
  int readWrappedCountsOnce() const override;

private:
  uint8_t m_pin = uint8_t(-1);
};
