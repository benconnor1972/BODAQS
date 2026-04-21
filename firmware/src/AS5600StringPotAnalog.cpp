#include "AS5600StringPotAnalog.h"

#include <Arduino.h>
#include <math.h>

#include "SensorRegistry.h"
#include "BoardSelect.h"

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
  if (params.getBool("invert", b))                 p.invert = b;
  if (params.getFloat("ema_alpha", d))             p.emaAlphaPermille = (uint16_t)lround(d * 1000.0);
  if (params.getInt("deadband", li))               p.deadbandCounts = (uint16_t)li;
  if (params.getInt("counts_per_turn", li))        p.countsPerTurn = (uint16_t)li;
  if (params.getInt("wrap_threshold_counts", li))  p.wrapThresholdCounts = (uint16_t)li;
  if (params.getInt("sensor_zero_count", li))      p.sensorZeroCount = (int32_t)li;
  if (params.getInt("sensor_full_count", li))      p.sensorFullCount = (int32_t)li;
  if (params.getFloat("sensor_full_travel_mm", d)) p.sensorFullTravelMm = (float)d;
  if (params.getInt("installed_zero_count", li))   p.installedZeroCount = (int32_t)li;
  if (params.getBool("assume_turn0_at_start", b))  p.assumeTurn0AtStart = b;
  if (params.getBool("include_raw", b))            p.includeRawColumn = b;
  if (params.get("units_label", s))                s.toCharArray(p.unitsLabel, sizeof(p.unitsLabel));

  long ain = -1;
  if (params.getInt("ain", ain) && board::gBoard) {
    const auto& bp = *board::gBoard;
    if (ain >= 0 && ain < (long)bp.analog.count) {
      const int pin = bp.analog.pins[(uint8_t)ain];
      if (pin >= 0) {
        p.pin = (uint8_t)pin;
      }
    }
  }
}

} // namespace

AS5600StringPotAnalog::AS5600StringPotAnalog(const Params& p)
  : AS5600StringPotSensorBase(p),
    m_pin(p.pin) {
}

void AS5600StringPotAnalog::begin() {
  pinMode(m_pin, INPUT);
  onLoggingStart();
}

bool AS5600StringPotAnalog::reconfigureFromSpec(const SensorSpec& spec) {
  if (spec.type != SensorType::AS5600StringPotAnalog) return false;

  Params p;
  loadParamsFromPack_(p, spec.name, spec.params);
  applyBaseParams(p);
  m_pin = p.pin;
  pinMode(m_pin, INPUT);
  onLoggingStart();
  return true;
}

int AS5600StringPotAnalog::readWrappedCountsOnce() const {
  return analogRead(m_pin);
}

const ParamDef* AS5600StringPotAnalog::paramDefs(size_t& count) {
  static const ParamDef defs[] = {
    {"ain",                   ParamType::Int,   "-1",    "-1",   "7",    nullptr, "Analog input ordinal (AIN0..). -1=use pin"},
    {"invert",                ParamType::Bool,  "false", nullptr, nullptr, nullptr, "Invert measurement direction"},
    {"ema_alpha",             ParamType::Float, "0.2",   "0",    "1",    nullptr, "EMA alpha [0..1]"},
    {"deadband",              ParamType::Int,   "0",     "0",    "4095", nullptr, "Deadband on unwrapped counts"},
    {"counts_per_turn",       ParamType::Int,   "4096",  "2",    "32767", nullptr, "Wrapped counts per AS5600 turn"},
    {"wrap_threshold_counts", ParamType::Int,   "2048",  "1",    "32767", nullptr, "Delta threshold used to detect wrap crossings"},
    {"sensor_zero_count",     ParamType::Int,   "0",     nullptr, nullptr, nullptr, "Unwrapped counts at zero travel"},
    {"sensor_full_count",     ParamType::Int,   "4095",  nullptr, nullptr, nullptr, "Unwrapped counts at full travel"},
    {"sensor_full_travel_mm", ParamType::Float, "0",     "0",    nullptr, nullptr, "Full sensor travel in mm for RANGE scaling"},
    {"installed_zero_count",  ParamType::Int,   "0",     nullptr, nullptr, nullptr, "Installed zero point in unwrapped counts"},
    {"assume_turn0_at_start", ParamType::Bool,  "true",  nullptr, nullptr, nullptr, "Reset unwrap state to turn 0 at each logging start"},
    {"output_mode",           ParamType::Enum,  "RAW,LINEAR,POLY,LUT", nullptr, nullptr, nullptr, "Output method: wrapped RAW, linear mm, or transformed mm"},
    {"include_raw",           ParamType::Bool,  "true",  nullptr, nullptr, nullptr, "Append wrapped RAW column after primary"},
    {"units_label",           ParamType::String,"mm",    nullptr, nullptr, nullptr, "Units suffix for LINEAR output"},
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
