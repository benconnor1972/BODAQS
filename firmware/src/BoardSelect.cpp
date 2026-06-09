#include "BoardSelect.h"
#include <ctype.h> 
#include <Arduino.h>
#include "DebugLog.h"

namespace board {

  const BoardProfile* gBoard = nullptr;

  void SelectBoard(BoardID id) {
    gBoard = &GetBoardProfile(id);
  }

  static bool equalsIgnoreCase_(const char* a, const char* b) {
    if (a == b) return true;
    if (!a || !b) return false;
    while (*a && *b) {
      char ca = (char)tolower((unsigned char)*a++);
      char cb = (char)tolower((unsigned char)*b++);
      if (ca != cb) return false;
    }
    return (*a == '\0' && *b == '\0');
  }

  int FindButtonIndexById(const char* id) {
    if (!id || !*id) return -1;
    if (!gBoard) return -1;

    const auto& bp = *gBoard;

    // Use the board’s declared count; btn[] itself is fixed-size (6 in your profile)
    const uint8_t n = bp.buttons.count;

    for (uint8_t i = 0; i < n; ++i) {
      const auto& b = bp.buttons.btn[i];
      if (!b.present) continue;
      if (equalsIgnoreCase_(b.id, id)) return (int)i;
    }
    return -1;
  }

  static const char* storageTypeName_(StorageType type) {
    switch (type) {
      case StorageType::SDMMC: return "SDMMC";
      case StorageType::None:
      default: return "None";
    }
  }

  static const char* rtcTypeName_(RtcType type) {
    switch (type) {
      case RtcType::RV3028: return "RV3028";
      case RtcType::None:
      default: return "None";
    }
  }

  static const char* externalAdcTypeName_(ExternalAdcType type) {
    switch (type) {
      case ExternalAdcType::ADS1220: return "ADS1220";
      case ExternalAdcType::None:
      default: return "None";
    }
  }

  static const char* analogSourceTypeName_(AnalogSourceType type) {
    switch (type) {
      case AnalogSourceType::InternalGpio: return "internal-gpio";
      case AnalogSourceType::ExternalAdc: return "external-adc";
      case AnalogSourceType::None:
      default: return "none";
    }
  }

  static const char* adcReferenceName_(AdcReferenceType reference) {
    switch (reference) {
      case AdcReferenceType::Internal: return "internal";
      case AdcReferenceType::ExternalRef0: return "external-ref0";
      case AdcReferenceType::ExternalRef1: return "external-ref1";
      case AdcReferenceType::AnalogSupply: return "analog-supply";
      case AdcReferenceType::Default:
      default: return "default";
    }
  }

  void DumpActiveBoardProfile() {
    if (!gBoard) {
      LOGW_TAG("Board", "gBoard=null\n");
      return;
    }

    const auto& bp = *gBoard;
    LOGI_TAG("Board", "Active profile: %s\n", bp.name ? bp.name : "(null)");

    LOGI_TAG("Board", "Storage: %s sdmmc_1bit=%u clk=%d cmd=%d d0=%d d1=%d d2=%d d3=%d det=%d active_low=%u pullup=%u\n",
             storageTypeName_(bp.storage.type),
             (unsigned)bp.storage.sdmmc_1bit,
             (int)bp.storage.sdmmc_clk,
             (int)bp.storage.sdmmc_cmd,
             (int)bp.storage.sdmmc_d0,
             (int)bp.storage.sdmmc_d1,
             (int)bp.storage.sdmmc_d2,
             (int)bp.storage.sdmmc_d3,
             (int)bp.storage.detect_pin,
             (unsigned)bp.storage.detect_active_low,
             (unsigned)bp.storage.detect_use_internal_pullup);

    LOGI_TAG("Board", "I2C buses: count=%u\n", (unsigned)bp.i2c_count);
    for (uint8_t i = 0; i < bp.i2c_count && i < BOARD_MAX_I2C_BUSES; ++i) {
      const auto& bus = bp.i2c[i];
      LOGI("  i2c%u present=%u sda=%d scl=%d hz=%lu\n",
           (unsigned)i,
           (unsigned)bus.present,
           (int)bus.sda,
           (int)bus.scl,
           (unsigned long)bus.hz);
    }

    LOGI_TAG("Board", "SPI: present=%u sck=%d miso=%d mosi=%d hz=%lu cs_count=%u\n",
             (unsigned)bp.spi.present,
             (int)bp.spi.sck,
             (int)bp.spi.miso,
             (int)bp.spi.mosi,
             (unsigned long)bp.spi.hz_default,
             (unsigned)bp.spi.cs_count);
    for (uint8_t i = 0; i < bp.spi.cs_count; ++i) {
      LOGI("  cs%u pin=%d\n", (unsigned)i, (int)bp.spi.cs_pins[i]);
    }

    LOGI_TAG("Board", "RTC: %s addr=0x%02X bus=%u int=%d\n",
             rtcTypeName_(bp.rtc.type),
             (unsigned)bp.rtc.i2c_addr,
             (unsigned)bp.rtc.bus_index,
             (int)bp.rtc.interrupt_pin);

    LOGI_TAG("Board", "Fuel: type=%u addr=0x%02X bus=%u alert=%d\n",
             (unsigned)bp.fuel.type,
             (unsigned)bp.fuel.i2c_addr,
             (unsigned)bp.fuel.bus_index,
             (int)bp.fuel.alert_pin);

    LOGI_TAG("Board", "External ADCs: count=%u\n", (unsigned)bp.external_adc_count);
    for (uint8_t i = 0; i < bp.external_adc_count && i < BOARD_MAX_EXTERNAL_ADCS; ++i) {
      const auto& adc = bp.external_adcs[i];
      LOGI("  adc%u type=%s cs=%d drdy=%d channels=%u max_sps=%lu ref=%s gain=%u pga_bypass=%u bits=%u\n",
           (unsigned)i,
           externalAdcTypeName_(adc.type),
           (int)adc.cs_pin,
           (int)adc.drdy_pin,
           (unsigned)adc.channel_count,
           (unsigned long)adc.max_sps,
           adcReferenceName_(adc.reference),
           (unsigned)adc.gain,
           (unsigned)adc.pga_bypass,
           (unsigned)adc.effective_bits);
    }

    LOGI_TAG("Board", "Analog: count=%u enable=%d active_high=%u default_on=%u adc_max=%u vref=%.3f\n",
             (unsigned)bp.analog.count,
             (int)bp.analog.enable_pin,
             (unsigned)bp.analog.enable_active_high,
             (unsigned)bp.analog.enable_default_on,
             (unsigned)bp.analog.adc_max,
             (double)bp.analog.vref);
    for (uint8_t i = 0; i < bp.analog.count && i < BOARD_MAX_ANALOG_INPUTS; ++i) {
      const auto& input = bp.analog.inputs[i];
      LOGI("  ain%u source=%s pin=%d adc=%u channel=%u differential=%u neg=%d legacy_pin=%d\n",
           (unsigned)i,
           analogSourceTypeName_(input.source),
           (int)input.pin,
           (unsigned)input.external_adc_index,
           (unsigned)input.external_channel,
           (unsigned)input.differential,
           (int)input.negative_channel,
           (int)bp.analog.pins[i]);
    }

    LOGI_TAG("Board", "Current limit: present=%u fault=%d active_low=%u pullup=%u\n",
             (unsigned)bp.current_limit.present,
             (int)bp.current_limit.fault_pin,
             (unsigned)bp.current_limit.fault_active_low,
             (unsigned)bp.current_limit.fault_use_internal_pullup);
  }

  void DumpActiveBoardButtons() {
    if (!gBoard) {
      LOGW_TAG("Board", "gBoard=null\n");
      return;
    }

    const auto& bp = *gBoard;
    LOGI_TAG("Board", "Buttons:\n");
    for (uint8_t i = 0; i < bp.buttons.count; ++i) {
      const auto& b = bp.buttons.btn[i];
      if (!b.present) continue;

      LOGI("  %u %-12s pin=%d mode=%s active_low=%u pullup=%u\n",
           (unsigned)i,
           b.id,
           (int)b.pin,
           (b.mode == 1) ? "poll" : "interrupt",
           (unsigned)b.active_low,
           (unsigned)b.use_internal_pullup);
    }
  }

} // namespace board
