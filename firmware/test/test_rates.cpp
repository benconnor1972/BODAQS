#include <cstdio>

#include "Rates.h"

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

    std::printf("Rates: %d passed, %d failed\n", passed, failed);
    return failed;
}
