#pragma once
#include <stddef.h>
#include <stdint.h>

// A session-bound mapping, in configured sensor order. Physical appointment
// order is independent: each ADC advances through only its own active channels.
class LocalAnalogRecordingPlan {
public:
  static constexpr unsigned kMaximumColumns = 32;
  struct Column {
    uint8_t sensorIndex = 0, adc = 0, channel = 0;
    int16_t pin = -1;
    bool external = false, primary = true;
  };
  bool configure(uint16_t rowHz) {
    *this = LocalAnalogRecordingPlan{};
    if (!rowHz || rowHz > 2000) return false;
    rowHz_ = rowHz;
    return true;
  }
  bool addExternal(uint8_t sensorIndex, uint8_t adc, uint8_t channel, bool primary=true) {
    if (!rowHz_ || columns_ >= kMaximumColumns || adc >= 2 || channel >= 4 ||
        (masks_[adc] & (1u << channel)) || uint32_t(rowHz_) * (channels(adc) + 1) > 2000)
      return false;
    fields_[columns_++] = {sensorIndex, adc, channel, -1, true, primary};
    if(primary) ++primaryColumns_;
    masks_[adc] |= 1u << channel;
    return true;
  }
  bool addGpio(uint8_t sensorIndex, int16_t pin, bool primary=true) {
    if (!rowHz_ || columns_ >= kMaximumColumns || pin < 0 || pin > 255) return false;
    for (unsigned i = 0; i < columns_; ++i)
      if (!fields_[i].external && fields_[i].pin == pin) return false;
    fields_[columns_++] = {sensorIndex, 0, 0, pin, false, primary};
    if(primary) ++primaryColumns_;
    return true;
  }
  unsigned inputs() const { return columns_; }
  unsigned columns() const { return primaryColumns_; }
  uint16_t rateHz() const { return rowHz_; }
  const Column& column(unsigned index) const { return fields_[index]; }
  uint8_t mask(unsigned adc) const { return adc < 2 ? masks_[adc] : 0; }
  unsigned channels(unsigned adc) const {
    unsigned count = 0;
    for (unsigned channel = 0; channel < 4; ++channel) count += (mask(adc) >> channel) & 1u;
    return count;
  }
  uint8_t firstChannel(unsigned adc) const {
    for (uint8_t channel = 0; channel < 4; ++channel)
      if (mask(adc) & (1u << channel)) return channel;
    return 255;
  }
  uint8_t nextChannel(unsigned adc, uint8_t current) const {
    for (unsigned offset = 1; offset <= 4; ++offset) {
      const uint8_t next = (current + offset) & 3u;
      if (mask(adc) & (1u << next)) return next;
    }
    return 255;
  }
private:
  Column fields_[kMaximumColumns];
  uint16_t rowHz_ = 0;
  uint8_t columns_ = 0, primaryColumns_=0, masks_[2] = {};
};

// Absolute rational deadlines, rounded upward so a wake hint never authorizes
// an early read. One claim produces at most one appointment per ADC and one row.
// Missed appointments do not change the identity of the conversion in flight.
class AdcAcquisitionCadence {
public:
  struct Due {
    uint64_t nextUs = UINT64_MAX, rowDeadlineUs = 0;
    uint32_t missed[2] = {}, sequence = 0, skippedRows = 0;
    uint8_t adcMask = 0;
    bool row = false;
  };
  bool begin(const LocalAnalogRecordingPlan& plan, uint64_t originUs) {
    if (!plan.rateHz()) return false;
    originUs_ = originUs;
    rates_[0] = plan.rateHz() * plan.channels(0);
    rates_[1] = plan.rateHz() * plan.channels(1);
    rates_[2] = plan.rateHz();
    for (auto& ordinal : claimed_) ordinal = 0;
    for (unsigned i = 0; i < 3; ++i)
      next_[i] = rates_[i] ? originUs_ + (1000000u + rates_[i] - 1) / rates_[i] : UINT64_MAX;
    return true;
  }
  Due claim(uint64_t nowUs) {
    Due result;
    for (unsigned timeline = 0; timeline < 3; ++timeline) {
      const uint64_t rate = rates_[timeline];
      if (!rate) continue;
      if (nowUs >= next_[timeline]) {
        const uint64_t ordinal = (nowUs - originUs_) * rate / 1000000u;
        const uint64_t skipped = ordinal - claimed_[timeline] - 1;
        if (timeline < 2) {
          result.adcMask |= 1u << timeline;
          result.missed[timeline] = bounded_(skipped);
        } else {
          result.row = true;
          result.sequence = static_cast<uint32_t>(ordinal - 1);
          result.skippedRows = bounded_(skipped);
          result.rowDeadlineUs = skipped ? originUs_ + (ordinal * 1000000u + rate - 1) / rate : next_[timeline];
        }
        claimed_[timeline] = ordinal;
        next_[timeline] = originUs_ + ((ordinal + 1) * 1000000u + rate - 1) / rate;
      }
      if (next_[timeline] < result.nextUs) result.nextUs = next_[timeline];
    }
    return result;
  }
private:
  static uint32_t bounded_(uint64_t value) { return value > UINT32_MAX ? UINT32_MAX : static_cast<uint32_t>(value); }
  uint64_t originUs_ = 0, claimed_[3] = {}, next_[3] = {UINT64_MAX, UINT64_MAX, UINT64_MAX};
  uint32_t rates_[3] = {};
};
