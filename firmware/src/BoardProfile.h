// BoardProfile.h
#pragma once
#include <stdint.h>
#include <stddef.h>

namespace board {

static constexpr uint8_t BOARD_MAX_BUTTONS = 6;
static constexpr uint8_t BOARD_MAX_I2C_BUSES = 2;
static constexpr uint8_t BOARD_MAX_ANALOG_INPUTS = 8;
static constexpr uint8_t BOARD_MAX_EXTERNAL_ADCS = 2;

// ---------- IDs / Types ----------
enum class BoardID : uint8_t {
  ThingPlusS3_BODAQS_4_D = 0,
  ThingPlusS3_BODAQS_4_D_UartI2C1,
  ThingPlusS3_BODAQS_4_F,
  BODAQS_V1RC3,
  BODAQS_S3_Mini_N4R2 = BODAQS_V1RC3,
  // Add more here...
};

enum class StorageType : uint8_t { None, SDMMC };
enum class DisplayType : uint8_t { None, OLED_SSD1306 };
enum class FuelGaugeType : uint8_t { None, MAX17048, Other };
enum class AdcAttenuation : uint8_t { Db0 = 0, Db2p5, Db6, Db11 };
enum class RtcType : uint8_t { None, RV3028 };
enum class ExternalAdcType : uint8_t { None, ADS1220 };
enum class AdcReferenceType : uint8_t { Default, Internal, ExternalRef0, ExternalRef1, AnalogSupply };
enum class AnalogSourceType : uint8_t { None, InternalGpio, ExternalAdc };
enum class ButtonID : uint8_t { BTN0=0, BTN1, BTN2, BTN3, BTN4, BTN5, Count };
enum class ButtonMode : uint8_t {Interrupt = 0, Poll = 1 };

// ---------- Sub-profiles ----------

struct StorageProfile {
  StorageType type = StorageType::None;

  // SDMMC configuration
  bool sdmmc_1bit = true;          // if you use SD_MMC 1-bit mode
  int8_t sdmmc_clk = -1;
  int8_t sdmmc_cmd = -1;
  int8_t sdmmc_d0  = -1;
  int8_t sdmmc_d1  = -1;   // optional (4-bit)
  int8_t sdmmc_d2  = -1;   // optional (4-bit)
  int8_t sdmmc_d3  = -1;   // optional (4-bit)

  // Optional socket card-detect switch. Not used by StorageManager yet.
  int8_t detect_pin = -1;
  bool detect_active_low = true;
  bool detect_use_internal_pullup = true;
};

struct ButtonHW {
  char id[16];
  bool present = false;
  int8_t pin = -1;
  uint8_t mode = 0; // 0 = interrupt, 1 = poll 
  bool active_low = true;
  bool use_internal_pullup = true;
};

struct ButtonsProfile {
  ButtonHW btn[6];     // fixed max, easy on embedded
  uint8_t count = 0;   // number actually present
};

struct DisplayProfile {
  DisplayType type = DisplayType::None;

  // If using I2C OLED
  uint8_t addr_primary = 0x3C;
  uint8_t addr_alt     = 0x3D;
  uint8_t bus_index    = 0;

  // Optional reset pin for the display (if wired)
  int8_t rst = -1;                 // -1 = not used
};

struct FuelGaugeProfile {
  FuelGaugeType type = FuelGaugeType::None;
  uint8_t i2c_addr = 0x36;         // MAX17048 default
  uint8_t bus_index = 0;

  // Optional alert/interrupt pin. MAX17048 ALRT is typically active-low/open-drain.
  int8_t alert_pin = -1;
  bool alert_active_low = true;
  bool alert_use_internal_pullup = true;
};

struct RtcProfile {
  RtcType type = RtcType::None;
  uint8_t i2c_addr = 0x52;         // RV3028 default
  uint8_t bus_index = 0;

  // Optional interrupt pin for future alarm/timer support.
  int8_t interrupt_pin = -1;
  bool interrupt_active_low = true;
  bool interrupt_use_internal_pullup = true;
};

struct I2CProfile {
  bool present = false;
  int8_t sda = -1, scl = -1;
  uint32_t hz = 400000;
};

struct SPIProfile {
  bool present = false;
  int8_t sck = -1, miso = -1, mosi = -1;
  uint32_t hz_default = 20000000;

  // “available CS pins” for other SPI devices (IMUs, ADCs, etc.)
  int8_t cs_pins[8] = {-1,-1,-1,-1,-1,-1,-1,-1};
  uint8_t cs_count = 0;
};

struct ExternalAdcProfile {
  ExternalAdcType type = ExternalAdcType::None;
  bool present = false;
  uint8_t spi_bus_index = 0;
  int8_t cs_pin = -1;
  int8_t drdy_pin = -1;
  bool drdy_active_low = true;
  bool drdy_use_internal_pullup = false;

  uint8_t channel_count = 0;
  uint32_t max_sps = 0;
  uint32_t spi_hz = 1000000;
  AdcReferenceType reference = AdcReferenceType::Default;
  uint8_t gain = 1;
  bool pga_bypass = true;
  uint8_t effective_bits = 12;
};

struct AnalogInputHW {
  AnalogSourceType source = AnalogSourceType::None;

  // Internal ESP32 ADC source.
  int8_t pin = -1;

  // External ADC source.
  uint8_t external_adc_index = 0;
  uint8_t external_channel = 0;
  bool differential = false;
  int8_t negative_channel = -1;
};

struct AnalogInputsProfile {
  // Numbered analog inputs AIN0..AIN(N-1)
  int8_t pins[BOARD_MAX_ANALOG_INPUTS] = {-1,-1,-1,-1,-1,-1,-1,-1};
  AnalogInputHW inputs[BOARD_MAX_ANALOG_INPUTS];
  uint8_t count = 0;

  // Optional switched analog rail control.
  // When present, firmware drives this to the default-on state at boot,
  // and disables it before sleep or when battery voltage is too low to log.
  int8_t enable_pin = -1;
  bool enable_active_high = true;
  bool enable_default_on = true;

  // Optional hints
  uint16_t adc_max = 4095;
  float vref = 3.3f;
  AdcAttenuation attenuation = AdcAttenuation::Db11;
};

struct IndicatorsProfile {
  bool has_led = false;
  int8_t led_pin = -1;
  bool led_active_high = true;

  bool has_buzzer = false;
  int8_t buzzer_pin = -1;
  bool buzzer_active_high = true;
};

struct CurrentLimitSwitchProfile {
  bool present = false;
  int8_t fault_pin = -1;
  bool fault_active_low = true;
  bool fault_use_internal_pullup = true;
};

struct LoggerPerfProfile {
  uint16_t queue_depth = 64;
  uint32_t ring_buffer_bytes = 8192;
};

// ---------- BoardProfile ----------
struct BoardProfile {
  const char* name = "Unknown";

  StorageProfile storage;
  DisplayProfile display;
  ButtonsProfile buttons;
  FuelGaugeProfile fuel;
  RtcProfile rtc;

  AnalogInputsProfile analog;
  I2CProfile i2c[BOARD_MAX_I2C_BUSES];
  uint8_t i2c_count = 0;
  SPIProfile spi;
  ExternalAdcProfile external_adcs[BOARD_MAX_EXTERNAL_ADCS];
  uint8_t external_adc_count = 0;

  IndicatorsProfile indicators;
  CurrentLimitSwitchProfile current_limit;
  LoggerPerfProfile perf;
};

// ---------- API ----------
const BoardProfile& GetBoardProfile(BoardID id);
const BoardProfile& GetBoardProfileByName(const char* name); // exact match (case-sensitive)

} // namespace board
