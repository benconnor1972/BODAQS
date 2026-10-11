#include "SensorAssignment.h"

SensorAssignment sensorAssignment(const SensorSpec& spec, const board::BoardProfile* bp) {
  SensorAssignment result;
  long bus = 0, address = 0;
  switch (spec.type) {
    case SensorType::BMI270ImuI2C: bus = 1; address = 0x68; break;
    case SensorType::AS5600AngleI2C:
    case SensorType::AS5600StringPotI2C: address = 0x36; break;
    case SensorType::AS5048BAngleI2C: address = 0x40; break;
    case SensorType::DANF10NGps:
      result.kind = SensorAssignment::Kind::Uart;
      spec.params.getInt("uart_port", bus);
      result.bus = bus;
      return result;
    case SensorType::AnalogPot:
    case SensorType::AS5600StringPotAnalog: {
      long ain = -1, pin = -1;
      spec.params.getInt("ain", ain);
      if (ain >= 0 && bp && ain < bp->analog.count && ain < board::BOARD_MAX_ANALOG_INPUTS) {
        const auto& input = bp->analog.inputs[ain];
        if (input.source == board::AnalogSourceType::ExternalAdc) {
          result.kind = SensorAssignment::Kind::ExternalAdc;
          result.bus = input.external_adc_index;
          result.input = input.external_channel;
          result.negativeInput = input.differential ? input.negative_channel : -1;
          return result;
        }
        pin = input.source == board::AnalogSourceType::InternalGpio ? input.pin : bp->analog.pins[ain];
      } else if (ain < 0) {
        spec.params.getInt("pin", pin);
      }
      if (pin >= 0 && pin <= 255) {
        result.kind = SensorAssignment::Kind::Gpio;
        result.input = pin;
      }
      return result;
    }
    default: return result;
  }
  spec.params.getInt("i2c_bus", bus);
  spec.params.getInt("i2c_addr", address);
  if (bus >= 0 && bus < board::BOARD_MAX_I2C_BUSES && address > 0 && address <= 0x7f) {
    result.kind = SensorAssignment::Kind::I2C;
    result.bus = bus;
    result.input = address;
  }
  return result;
}

bool assignmentsConflict(const SensorAssignment& a, const SensorAssignment& b) {
  if (a.kind == SensorAssignment::Kind::None || a.kind != b.kind || a.bus != b.bus) return false;
  if (a.kind == SensorAssignment::Kind::Uart) return true;
  if (a.input == b.input) return true;
  return a.kind == SensorAssignment::Kind::ExternalAdc &&
      ((a.negativeInput >= 0 && (a.negativeInput == b.input || a.negativeInput == b.negativeInput)) ||
       (b.negativeInput >= 0 && b.negativeInput == a.input));
}

const char* assignmentOwner(const SensorAssignment& a, const board::BoardProfile* bp) {
  if (!bp || a.kind != SensorAssignment::Kind::I2C) return nullptr;
  if (bp->fuel.type != board::FuelGaugeType::None && a.bus == bp->fuel.bus_index && a.input == bp->fuel.i2c_addr) return "fuel gauge";
  if (bp->rtc.type != board::RtcType::None && a.bus == bp->rtc.bus_index && a.input == bp->rtc.i2c_addr) return "RTC";
  if (bp->display.type != board::DisplayType::None && a.bus == bp->display.bus_index &&
      (a.input == bp->display.addr_primary || a.input == bp->display.addr_alt)) return "OLED";
  return nullptr;
}
