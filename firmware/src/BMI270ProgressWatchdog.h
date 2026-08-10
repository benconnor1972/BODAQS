#pragma once

#include <stdint.h>

class BMI270ProgressWatchdog {
public:
  explicit constexpr BMI270ProgressWatchdog(uint32_t timeoutUs)
      : timeoutUs_(timeoutUs) {
  }

  void arm(uint32_t nowUs) {
    lastProgressUs_ = nowUs;
    armed_ = true;
  }

  void disarm() { armed_ = false; }

  void recordProgress(uint32_t nowUs) { arm(nowUs); }

  bool expired(uint32_t nowUs) const {
    return armed_ && elapsedUs(nowUs) >= timeoutUs_;
  }

  uint32_t elapsedUs(uint32_t nowUs) const {
    return armed_ ? static_cast<uint32_t>(nowUs - lastProgressUs_) : 0;
  }

  uint32_t timeoutUs() const { return timeoutUs_; }
  bool armed() const { return armed_; }

private:
  uint32_t timeoutUs_ = 0;
  uint32_t lastProgressUs_ = 0;
  bool armed_ = false;
};

class BMI270RecoveryBudget {
public:
  explicit constexpr BMI270RecoveryBudget(uint8_t maximumAttempts)
      : maximumAttempts_(maximumAttempts) {
  }

  bool reserveAttempt() {
    if (attemptsWithoutProgress_ >= maximumAttempts_) return false;
    ++attemptsWithoutProgress_;
    return true;
  }

  void recordProgress() { attemptsWithoutProgress_ = 0; }
  void reset() { attemptsWithoutProgress_ = 0; }

  bool exhausted() const {
    return attemptsWithoutProgress_ >= maximumAttempts_;
  }

  uint8_t attemptsWithoutProgress() const { return attemptsWithoutProgress_; }
  uint8_t maximumAttempts() const { return maximumAttempts_; }

private:
  uint8_t maximumAttempts_ = 0;
  uint8_t attemptsWithoutProgress_ = 0;
};
