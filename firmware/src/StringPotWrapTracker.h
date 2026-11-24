#pragma once

#include <stdint.h>

// Tracks accepted samples separately from raw ADC readings. An analog rollover
// can settle through midscale, splitting a full-turn jump below the wrap
// threshold. Keep the endpoint as the reference during that short transition.
class StringPotWrapTracker {
public:
  void reset(int wrapped, int32_t unwrapped, int modulus) {
    m_lastWrapped = wrapped;
    m_unwrapped = unwrapped;
    m_turn = (int64_t(unwrapped) - wrapped) / modulus;
    m_pendingSamples = 0;
    m_overflow = false;
    m_settlingTimedOut = false;
  }

  int32_t update(int wrapped, int modulus, int threshold, bool analog) {
    m_settlingTimedOut=false;
    if(m_overflow) return m_unwrapped;
    const int delta = wrapped - m_lastWrapped;
    if (analog) {
      const int edge = modulus / 8;
      const bool interior = wrapped > edge && wrapped < modulus - edge;
      if (!interior) {
        m_pendingSamples = 0;
      } else if (m_pendingSamples) {
        // Bound the hold even if the input stops in the middle of its range.
        if (--m_pendingSamples) return m_unwrapped;
        m_settlingTimedOut=true;
      } else {
        const int rapidStep = threshold / 4 > 0 ? threshold / 4 : 1;
        const bool leavingLow = m_lastWrapped <= edge && delta >= rapidStep;
        const bool leavingHigh = m_lastWrapped >= modulus - edge && delta <= -rapidStep;
        if (leavingLow || leavingHigh) {
          m_pendingSamples = 3;
          return m_unwrapped;
        }
      }
    }

    if (delta <= -threshold) ++m_turn;
    else if (delta >= threshold) --m_turn;
    m_lastWrapped = wrapped;
    const int64_t candidate=m_turn * int64_t(modulus) + wrapped;
    if(candidate>INT32_MAX || candidate<INT32_MIN) {
      m_overflow=true;
      m_unwrapped=candidate>INT32_MAX?INT32_MAX:INT32_MIN;
    } else m_unwrapped=static_cast<int32_t>(candidate);
    return m_unwrapped;
  }
  bool settlingHeld() const {return m_pendingSamples!=0;}
  bool overflowed() const {return m_overflow;}
  bool settlingTimedOut() const {return m_settlingTimedOut;}

private:
  int m_lastWrapped = 0;
  int32_t m_unwrapped = 0;
  int64_t m_turn = 0;
  uint8_t m_pendingSamples = 0;
  bool m_overflow = false;
  bool m_settlingTimedOut = false;
};
