#include "AS5600StringPotAnalog.h"

#include <Arduino.h>
#include <math.h>

#include "SensorRegistry.h"
#include "BoardSelect.h"
#include "AnalogInputManager.h"

namespace {

void loadParamsFromPack_(AS5600StringPotAnalog::Params& p,
                         const char* instanceName,
                         const ParamPack& params) {
  p.name = instanceName ? instanceName : "as5600";

  long li = 0;
  bool b = false;
  double d = 0.0;
  String s;

  if (params.getInt("pin", li))                    p.pin = (uint8_t)li;
  if (params.getInt("ain", li))                    p.ain = (int8_t)li;
  if (params.getInt("counts_per_turn", li))        p.countsPerTurn = (uint16_t)li;
  if (params.getInt("wrap_threshold_counts", li))  p.wrapThresholdCounts = (uint16_t)li;
  if (params.getInt("sensor_zero_count", li))      p.sensorZeroCount = (int32_t)li;
  if (params.getInt("sensor_full_count", li))      p.sensorFullCount = (int32_t)li;
  if (params.getFloat("sensor_full_travel_mm", d)) p.sensorFullTravelMm = (float)d;
  if (params.getInt("installed_zero_count", li))   p.installedZeroCount = (int32_t)li;
  if (params.getBool("assume_turn0_at_start", b))  p.assumeTurn0AtStart = b;
  if (params.getBool("include_raw", b))            p.includeRawColumn = b;
  if (params.get("end", s))                        s.toCharArray(p.semanticEnd, sizeof(p.semanticEnd));
  if (params.get("primary_domain", s))             s.toCharArray(p.primaryDomain, sizeof(p.primaryDomain));
  if (params.get("primary_quantity", s))           s.toCharArray(p.primaryQuantity, sizeof(p.primaryQuantity));

  long ain = -1;
  if (params.getInt("ain", ain) && board::gBoard) {
    const auto& bp = *board::gBoard;
    if (ain >= 0 && ain < (long)bp.analog.count) {
      const int pin = AnalogInputManager::pinForAin((uint8_t)ain);
      if (pin >= 0) {
        p.pin = (uint8_t)pin;
      }
    }
  }
}

} // namespace

AS5600StringPotAnalog::AS5600StringPotAnalog(const Params& p)
  : AS5600StringPotSensorBase(p),
    m_ain(p.ain),
    m_pin(p.pin) {
}

void AS5600StringPotAnalog::begin() {
  if (m_ain < 0 && m_pin != uint8_t(-1)) {
    pinMode(m_pin, INPUT);
  }
  onLoggingStart();
}

bool AS5600StringPotAnalog::reconfigureFromSpec(const SensorSpec& spec) {
  if (spec.type != SensorType::AS5600StringPotAnalog) return false;

  Params p;
  loadParamsFromPack_(p, spec.name, spec.params);
  applyBaseParams(p);
  m_ain = p.ain;
  m_pin = p.pin;
  if (m_ain < 0 && m_pin != uint8_t(-1)) {
    pinMode(m_pin, INPUT);
  }
  onLoggingStart();
  return true;
}

int AS5600StringPotAnalog::readWrappedCountsOnce() const {
  if (m_ain >= 0) {
    int32_t counts = 0;
    if (AnalogInputManager::readCounts((uint8_t)m_ain, counts)) {
      return (int)counts;
    }
    return 0;
  }

  return analogRead(m_pin);
}

const ParamDef* AS5600StringPotAnalog::paramDefs(size_t& count) {
  static const ParamDef defs[] = {
    {"ain",                   ParamType::Int,   "-1",    "-1",   "7",    nullptr, "Analog input ordinal (AIN0..). -1=use pin"},
    {"counts_per_turn",       ParamType::Int,   "4096",  "2",    "32767", nullptr, "Wrapped counts per AS5600 turn"},
    {"wrap_threshold_counts", ParamType::Int,   "2048",  "1",    "32767", nullptr, "Delta threshold used to detect wrap crossings"},
    {"sensor_zero_count",     ParamType::Int,   "0",     nullptr, nullptr, nullptr, "Unwrapped counts at zero travel"},
    {"sensor_full_count",     ParamType::Int,   "4095",  nullptr, nullptr, nullptr, "Unwrapped counts at full travel"},
    {"sensor_full_travel_mm", ParamType::Float, "0",     "0",    nullptr, nullptr, "Full sensor travel in mm for RANGE scaling"},
    {"installed_zero_count",  ParamType::Int,   "0",     nullptr, nullptr, nullptr, "Installed zero point in unwrapped counts"},
    {"assume_turn0_at_start", ParamType::Bool,  "true",  nullptr, nullptr, nullptr, "Reset unwrap state to turn 0 at each logging start"},
    {"output_mode",           ParamType::Enum,  "RAW,LINEAR,POLY,LUT", nullptr, nullptr, nullptr, "Output method: wrapped RAW, linear mm, or transformed mm"},
    {"include_raw",           ParamType::Bool,  "true",  nullptr, nullptr, nullptr, "Append wrapped and unwrapped RAW columns"},
    {"end",                   ParamType::Enum,  "",      nullptr, nullptr, "front,rear", "Optional semantic end for log metadata"},
    {"primary_domain",        ParamType::Enum,  "",      nullptr, nullptr, "wheel,suspension,brake,drivetrain,frame,steering", "Optional semantic domain for primary output"},
    {"primary_quantity",      ParamType::Enum,  "",      nullptr, nullptr, "disp,ang_disp,force,pressure,temp,voltage,norm", "Optional semantic quantity for primary output"},
  };

  count = sizeof(defs) / sizeof(defs[0]);
  return defs;
}

Sensor* AS5600StringPotAnalog::create(const char* instanceName, const ParamPack& params, bool mutedDefault) {
  Params p;
  loadParamsFromPack_(p, instanceName, params);

  auto* obj = new AS5600StringPotAnalog(p);
  obj->setMuted(mutedDefault);
  return obj;
}

static bool _reg_as5600_analog =
  SensorRegistry::registerType(
    SensorType::AS5600StringPotAnalog,
    "as5600_string_pot_analog",
    "AS5600 String Pot (Analog)",
    &AS5600StringPotAnalog::paramDefs,
    &AS5600StringPotAnalog::create,
    (CalModeMask)(CAL_ZERO | CAL_RANGE)
  );
