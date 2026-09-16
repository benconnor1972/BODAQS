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

    std::printf("Rates: %d passed, %d failed\n", passed, failed);
    return failed;
}
