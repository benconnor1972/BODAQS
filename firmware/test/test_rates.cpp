#include <cstdio>

#include "Rates.h"
#include "I2CSchedulePlan.h"

int runRateTests() {
    int passed = 0;
    int failed = 0;

    auto check = [&](bool condition, const char* description) {
        if (condition) {
            ++passed;
        } else {
            std::printf("    FAIL: test_rates: %s\n", description);
            ++failed;
        }
    };

    check(Rates::isSupported(700) && Rates::nearest(700) == 700,
          "700 Hz is accepted and preserved when loading configuration");
    check(Rates::nearest(650) == 700 && Rates::nearest(850) == 700,
          "configuration rounding includes 700 Hz and keeps the lower rate on ties");
    check(!Rates::isSupported(701),
          "rates outside the permitted list remain unsupported");
    check(Rates::periodUs(700) == 1428,
          "700 Hz uses the existing integer-microsecond period policy");
    check(Rates::periodUs(1000) == 1000,
          "1000 Hz cadence retains a 1000 us period");
    check(Rates::periodUs(500) == 2000 && Rates::periodUs(200) == 5000,
          "existing logger rates retain exact periods");
    check(Rates::scheduledTimeUs(123456789ULL, 3, 1000) == 123459789ULL,
          "scheduled timestamps stay on the microsecond grid");
    check(Rates::missedSlots(999, 1000) == 0 &&
              Rates::missedSlots(1000, 1000) == 1 &&
              Rates::missedSlots(2501, 1000) == 2,
          "missed slots use the configured microsecond period");
    check(I2CSchedulePlan::staggerOffsetUs(20000, 0, 2) == 0 &&
              I2CSchedulePlan::staggerOffsetUs(20000, 1, 2) == 10000,
          "equal-rate I2C clients are staggered across their shared period");
    check(I2CSchedulePlan::staggerOffsetUs(10000, 2, 4) == 5000,
          "I2C phase staggering scales to more than two peers");
    check(I2CSchedulePlan::nextTieCursor(5, 8) == 6 &&
              I2CSchedulePlan::nextTieCursor(7, 8) == 0,
          "I2C overdue-tie selection rotates through the client table");
    check(I2CSchedulePlan::shouldYieldToLatencySensitive(
              15000, 3000, 2000, 29000, true, 50000, 0, 1),
          "buffered I2C service yields when a latency deadline falls inside its transfer");
    check(!I2CSchedulePlan::shouldYieldToLatencySensitive(
               15000, 16000, 2000, 29000, true, 50000, 0, 1),
          "buffered I2C service does not yield for a deadline beyond its transfer");
    check(!I2CSchedulePlan::shouldYieldToLatencySensitive(
               15000, 3000, 2000, 0, false, 50000, 0, 1),
          "buffered I2C service establishes progress before allowing priority yields");
    check(!I2CSchedulePlan::shouldYieldToLatencySensitive(
               15000, 1000, 2000, 48000, true, 50000, 0, 1),
          "latency priority cannot exceed the buffered client's maximum service gap");
    check(I2CSchedulePlan::shouldYieldToLatencySensitive(
              15000, 3000, 2000, 45000, true, 70000, 1, 2),
          "a buffered client may use a second admitted priority yield");
    check(!I2CSchedulePlan::shouldYieldToLatencySensitive(
               15000, 3000, 2000, 45000, true, 70000, 2, 2),
          "latency priority stops at the per-service yield limit");

    std::printf("Rates: %d passed, %d failed\n", passed, failed);
    return failed;
}
