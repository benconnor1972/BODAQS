#include "SensorAssignment.h"
#include <strings.h>
#include <stdlib.h>

namespace {
enum class ProviderParse : uint8_t { Local, CanNode, Invalid };

ProviderParse parseProvider_(const SensorSpec& spec, SensorProviderId& provider) {
  char text[16] = {0};
  if (!spec.params.get("provider", text, sizeof(text)) || !text[0] ||
      !strcasecmp(text, "local")) {
    provider = SensorProviderId{};
    return ProviderParse::Local;
  }

  const char* number = nullptr;
  if (!strncasecmp(text, "can:", 4)) number = text + 4;
  else if (!strncasecmp(text, "can", 3)) number = text + 3;
  if (!number || !*number) return ProviderParse::Invalid;

  char* end = nullptr;
  const long index = strtol(number, &end, 10);
  if (!end || *end || index < 0 || index >= MAX_CAN_SENSOR_NODES) {
    return ProviderParse::Invalid;
  }
  provider.kind = SensorProviderKind::CanNode;
  provider.index = (uint8_t)index;
  return ProviderParse::CanNode;
}

SensorAssignment remoteAssignment_(const SensorSpec& spec, const SensorProviderId& provider) {
  SensorAssignment result;
  result.provider = provider;

  char endpoint[16] = {0};
  if (!spec.params.get("endpoint", endpoint, sizeof(endpoint))) return result;
  if (!strcasecmp(endpoint, "imu")) {
    result.kind = SensorAssignment::Kind::NodeImu;
    result.input = 0;
    return result;
  }

  const char* number = nullptr;
  if (!strncasecmp(endpoint, "ain:", 4)) {
    result.kind = SensorAssignment::Kind::NodeAnalog;
    number = endpoint + 4;
  } else if (!strncasecmp(endpoint, "analog:", 7)) {
    result.kind = SensorAssignment::Kind::NodeAnalog;
    number = endpoint + 7;
  } else if (!strncasecmp(endpoint, "i2c:", 4)) {
    result.kind = SensorAssignment::Kind::NodeI2C;
    number = endpoint + 4;
  } else {
    return SensorAssignment{};
  }

  char* end = nullptr;
  const long port = strtol(number, &end, 10);
  if (!end || *end || port < 0 || port > 1) return SensorAssignment{};
  result.input = (int16_t)port;
  return result;
}
}

SensorAssignment sensorAssignment(const SensorSpec& spec, const board::BoardProfile* bp) {
  SensorAssignment result;
  SensorProviderId provider;
  const ProviderParse providerParse = parseProvider_(spec, provider);
  if (providerParse == ProviderParse::CanNode) return remoteAssignment_(spec, provider);
  if (providerParse == ProviderParse::Invalid) return result;
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
  if (a.kind == SensorAssignment::Kind::None || a.provider != b.provider ||
      a.kind != b.kind || a.bus != b.bus) return false;
  if (a.kind == SensorAssignment::Kind::Uart) return true;
  if (a.input == b.input) return true;
  return a.kind == SensorAssignment::Kind::ExternalAdc &&
      ((a.negativeInput >= 0 && (a.negativeInput == b.input || a.negativeInput == b.negativeInput)) ||
       (b.negativeInput >= 0 && b.negativeInput == a.input));
}

const char* assignmentOwner(const SensorAssignment& a, const board::BoardProfile* bp) {
  if (!bp || a.provider.kind != SensorProviderKind::Local ||
      a.kind != SensorAssignment::Kind::I2C) return nullptr;
  if (bp->fuel.type != board::FuelGaugeType::None && a.bus == bp->fuel.bus_index && a.input == bp->fuel.i2c_addr) return "fuel gauge";
  if (bp->rtc.type != board::RtcType::None && a.bus == bp->rtc.bus_index && a.input == bp->rtc.i2c_addr) return "RTC";
  if (bp->display.type != board::DisplayType::None && a.bus == bp->display.bus_index &&
      (a.input == bp->display.addr_primary || a.input == bp->display.addr_alt)) return "OLED";
  return nullptr;
}
