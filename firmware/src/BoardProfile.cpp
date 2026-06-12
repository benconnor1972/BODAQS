#include <Arduino.h>
#include "BoardProfile.h"
#include <string.h>

namespace board {

static constexpr int8_t kDefaultUartTxPin = 43;
static constexpr int8_t kDefaultUartRxPin = 44;

static SPIProfile MakeSPI(bool present, int8_t sck, int8_t miso, int8_t mosi,
                          const int8_t* cs_list, uint8_t cs_count,
                          uint32_t hz = 20000000) {
  SPIProfile p;
  p.present = present;
  p.sck = sck;
  p.miso = miso;
  p.mosi = mosi;
  p.hz_default = hz;
  p.cs_count = (cs_count > 8) ? 8 : cs_count;
  for (uint8_t i = 0; i < 8; ++i) p.cs_pins[i] = -1;
  for (uint8_t i = 0; i < p.cs_count; ++i) p.cs_pins[i] = cs_list[i];
  return p;
}

static UARTProfile MakeUART(bool present, int8_t tx, int8_t rx,
                            uint32_t baud = 38400) {
  UARTProfile p;
  p.present = present;
  p.tx = tx;
  p.rx = rx;
  p.baud_default = baud;
  return p;
}

static AnalogInputHW MakeInternalAnalog(int8_t pin) {
  AnalogInputHW input;
  input.source = (pin >= 0) ? AnalogSourceType::InternalGpio : AnalogSourceType::None;
  input.pin = pin;
  return input;
}

static AnalogInputHW MakeExternalAdcInput(uint8_t adcIndex, uint8_t channel) {
  AnalogInputHW input;
  input.source = AnalogSourceType::ExternalAdc;
  input.external_adc_index = adcIndex;
  input.external_channel = channel;
  input.differential = false;
  input.negative_channel = -1;
  return input;
}

static const BoardProfile THING_PLUS_S3_BODAQS_4_D = {
  .name = "BODAQS 4D",

  .storage = {
    .type = StorageType::SDMMC,
    .sdmmc_1bit = true,
    .sdmmc_clk = 38,
    .sdmmc_cmd = 34,
    .sdmmc_d0  = 39,
  },

  .display = {
    .type = DisplayType::OLED_SSD1306,
    .addr_primary = 0x3C,
    .addr_alt     = 0x3D,
    .bus_index    = 0,
    .rst = -1
  },

  .buttons = {
    .btn = {
      { "nav_up",    true, 6, 1, true,  true },
      { "nav_down",  true, 7, 1, true,  true },
      { "nav_left",  true, 5, 1, true,  true },
      { "nav_right", true, 4, 1, true,  true },
      { "nav_enter", true, 21, 0, true,  true },
      { "mark",      true, 2, 0, true,  true },
    },
    .count = 6,
  },

  .fuel = {
    .type = FuelGaugeType::MAX17048,
    .i2c_addr = 0x36,
    .bus_index = 0
  },

  .analog = {
    .pins  = { 15, 17, 18, 10, -1, -1, -1, -1 },
    .inputs = {
      MakeInternalAnalog(15),
      MakeInternalAnalog(17),
      MakeInternalAnalog(18),
      MakeInternalAnalog(10),
    },
    .count = 4,
    .adc_max = 4095,
    .vref = 3.3f,
    .attenuation = AdcAttenuation::Db11
  },

  .i2c = {
    {
      .present = true,
      .sda = 8,
      .scl = 9,
      .hz  = 400000
    }
  },
  .i2c_count = 1,

  .spi = MakeSPI(
    true,
    -1,
    -1,
    -1,
    (const int8_t[]){ -1 },
    0,
    20000000
  ),

  .indicators = {
    .has_led = true,
    .led_pin = 1,
    .led_active_high = true,
    .has_buzzer = false,
    .buzzer_pin = -1,
    .buzzer_active_high = true
  },

  .perf = {
    .queue_depth = 256,
    .ring_buffer_bytes = 32768
  }
};

static const BoardProfile THING_PLUS_S3_BODAQS_4_D_UART_I2C1 = [] {
  BoardProfile p = THING_PLUS_S3_BODAQS_4_D;
  p.name = "BODAQS 4D (UART as I2C1)";
  p.i2c[1] = {
    .present = true,
    .sda = TX,
    .scl = RX,
    .hz  = 100000
  };
  p.i2c_count = 2;
  return p;
}();

static const BoardProfile THING_PLUS_S3_BODAQS_4_F = [] {
  BoardProfile p = THING_PLUS_S3_BODAQS_4_D;
  p.name = "BODAQS 4F";

  p.buttons.btn[0] = ButtonHW{ "nav_up",    true, 6,  1, true, true };
  p.buttons.btn[1] = ButtonHW{ "nav_down",  true, 5,  1, true, true };
  p.buttons.btn[2] = ButtonHW{ "nav_left",  true, 7,  1, true, true };
  p.buttons.btn[3] = ButtonHW{ "nav_right", true, 21, 1, true, true };
  p.buttons.btn[4] = ButtonHW{ "nav_enter", true, 4,  0, true, true };
  p.analog.pins[0] = 10;
  p.analog.pins[1] = 18;
  p.analog.pins[2] = 17;
  p.analog.pins[3] = 15;
  p.analog.inputs[0] = MakeInternalAnalog(10);
  p.analog.inputs[1] = MakeInternalAnalog(18);
  p.analog.inputs[2] = MakeInternalAnalog(17);
  p.analog.inputs[3] = MakeInternalAnalog(15);

  p.i2c[0] = {
    .present = true,
    .sda = 8,
    .scl = 9,
    .hz  = 400000
  };
  p.i2c[1] = {
    .present = true,
    .sda = 14,
    .scl = 16,
    .hz  = 100000
  };
  p.i2c_count = 2;
  p.uart[0] = MakeUART(true, kDefaultUartTxPin, kDefaultUartRxPin);
  p.uart_count = 1;
  p.analog.attenuation = AdcAttenuation::Db6;
  p.analog.enable_pin = 42;
  p.analog.enable_active_high = true;
  p.analog.enable_default_on = true;

  return p;
}();

static const BoardProfile V1RC3_PROFILE = {
  .name = "BODAQS V1RC3",

  .storage = {
    .type = StorageType::SDMMC,
    .sdmmc_1bit = false,
    .sdmmc_clk = 10,
    .sdmmc_cmd = 9,
    .sdmmc_d0  = 11,
    .sdmmc_d1  = 12,
    .sdmmc_d2  = 7,
    .sdmmc_d3  = 8,
    .detect_pin = 6,
    .detect_active_low = true,
    .detect_use_internal_pullup = true,
  },

  .display = {
    .type = DisplayType::OLED_SSD1306,
    .addr_primary = 0x3C,
    .addr_alt     = 0x3D,
    .bus_index    = 0,
    .rst = -1
  },

  .buttons = {
    .btn = {
      { "nav_up",    true, 17, 1, true, true },
      { "nav_down",  true, 13, 1, true, true },
      { "nav_left",  true, 14, 1, true, true },
      { "nav_right", true, 15, 1, true, true },
      { "nav_enter", true, 16, 0, true, true },
      { "mark",      true, 42, 0, true, true },
    },
    .count = 6,
  },

  .fuel = {
    .type = FuelGaugeType::MAX17048,
    .i2c_addr = 0x36,
    .bus_index = 0,
    .alert_pin = 33,
    .alert_active_low = true,
    .alert_use_internal_pullup = true
  },

  .rtc = {
    .type = RtcType::RV3028,
    .i2c_addr = 0x52,
    .bus_index = 0,
    .interrupt_pin = -1,
    .interrupt_active_low = true,
    .interrupt_use_internal_pullup = true
  },

  .analog = {
    .pins  = { -1, -1, -1, -1, -1, -1, -1, -1 },
    .inputs = {
      MakeExternalAdcInput(0, 0),
      MakeExternalAdcInput(0, 1),
      MakeExternalAdcInput(0, 2),
      MakeExternalAdcInput(0, 3),
      MakeExternalAdcInput(1, 0),
      MakeExternalAdcInput(1, 1),
      MakeExternalAdcInput(1, 2),
      MakeExternalAdcInput(1, 3),
    },
    .count = 8,
    .enable_pin = 35,
    .enable_active_high = true,
    .enable_default_on = true,
    .adc_max = 4095,
    .vref = 3.3f,
    .attenuation = AdcAttenuation::Db11
  },

  .i2c = {
    {
      .present = true,
      .sda = 1,
      .scl = 2,
      .hz  = 400000
    },
    {
      .present = true,
      .sda = 4,
      .scl = 5,
      .hz  = 100000
    }
  },
  .i2c_count = 2,

  .uart = {
    {
      .present = true,
      .tx = kDefaultUartTxPin,
      .rx = kDefaultUartRxPin,
      .baud_default = 38400
    }
  },
  .uart_count = 1,

  .spi = MakeSPI(
    true,
    37,
    39,
    38,
    (const int8_t[]){ 47, 21, 40 },
    3,
    20000000
  ),

  .external_adcs = {
    {
      .type = ExternalAdcType::ADS1220,
      .present = true,
      .spi_bus_index = 0,
      .cs_pin = 47,
      .drdy_pin = 36,
      .drdy_active_low = true,
      .drdy_use_internal_pullup = false,
      .channel_count = 4,
      .max_sps = 2000,
      .spi_hz = 1000000,
      .reference = AdcReferenceType::ExternalRef0,
      .gain = 1,
      .pga_bypass = true,
      .effective_bits = 12
    },
    {
      .type = ExternalAdcType::ADS1220,
      .present = true,
      .spi_bus_index = 0,
      .cs_pin = 21,
      .drdy_pin = 18,
      .drdy_active_low = true,
      .drdy_use_internal_pullup = false,
      .channel_count = 4,
      .max_sps = 2000,
      .spi_hz = 1000000,
      .reference = AdcReferenceType::ExternalRef0,
      .gain = 1,
      .pga_bypass = true,
      .effective_bits = 12
    }
  },
  .external_adc_count = 2,

  .indicators = {
    .has_led = false,
    .led_pin = -1,
    .led_active_high = true,
    .has_buzzer = false,
    .buzzer_pin = -1,
    .buzzer_active_high = true
  },

  .current_limit = {
    .present = true,
    .fault_pin = 34,
    .fault_active_low = true,
    .fault_use_internal_pullup = true
  },

  .perf = {
    .queue_depth = 256,
    .ring_buffer_bytes = 32768
  }
};

const BoardProfile& GetBoardProfile(BoardID id) {
  switch (id) {
    case BoardID::ThingPlusS3_BODAQS_4_D: return THING_PLUS_S3_BODAQS_4_D;
    case BoardID::ThingPlusS3_BODAQS_4_D_UartI2C1: return THING_PLUS_S3_BODAQS_4_D_UART_I2C1;
    case BoardID::ThingPlusS3_BODAQS_4_F: return THING_PLUS_S3_BODAQS_4_F;
    case BoardID::BODAQS_V1RC3: return V1RC3_PROFILE;
    default: return THING_PLUS_S3_BODAQS_4_D;
  }
}

const BoardProfile& GetBoardProfileByName(const char* name) {
  if (!name) return THING_PLUS_S3_BODAQS_4_D;

  if (strcmp(name, THING_PLUS_S3_BODAQS_4_D.name) == 0) return THING_PLUS_S3_BODAQS_4_D;
  if (strcmp(name, THING_PLUS_S3_BODAQS_4_D_UART_I2C1.name) == 0) return THING_PLUS_S3_BODAQS_4_D_UART_I2C1;
  if (strcmp(name, THING_PLUS_S3_BODAQS_4_F.name) == 0) return THING_PLUS_S3_BODAQS_4_F;
  if (strcmp(name, V1RC3_PROFILE.name) == 0) return V1RC3_PROFILE;
  if (strcmp(name, "BODAQS S3 Mini N4R2") == 0) return V1RC3_PROFILE;

  return THING_PLUS_S3_BODAQS_4_D;
}

} // namespace board
