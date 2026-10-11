#include <cstdio>
#include "AdcReadyWait.h"

int runAdcReadyWaitTests() {
    int passed = 0;
    int failed = 0;
    auto check = [&](bool condition, const char* description) {
        if (condition) ++passed;
        else {
            std::printf("    FAIL: test_adc_ready_wait: %s\n", description);
            ++failed;
        }
    };

    uint32_t now = 0;
    unsigned blocks = 0;
    auto clock = [&]() { return now; };
    auto result = AdcReadyWait::wait(5500, clock, []() { return true; },
        [&](uint32_t) { ++blocks; });
    check(result.ready && result.elapsedUs == 0 && blocks == 0,
          "conversion complete before wait does not require another DRDY edge");

    bool ready = false;
    result = AdcReadyWait::wait(5500, clock, [&]() { return ready; },
        [&](uint32_t) { ++blocks; now += 500; ready = true; });
    check(result.ready && result.elapsedUs == 500 && blocks == 1,
          "normal conversion blocks and wakes at DRDY without a tick-sized delay");

    // An ISR fires after the level check but before ulTaskNotifyTake. The
    // pending notification must make that call return without waiting.
    ready = false;
    blocks = 0;
    result = AdcReadyWait::wait(5500, clock, [&]() {
        if (!ready) { ready = true; return false; }
        return true;
    }, [&](uint32_t) { ++blocks; });
    check(result.ready && result.elapsedUs == 0 && blocks == 1,
          "completion between level check and notification wait is retained");

    ready = false;
    blocks = 0;
    result = AdcReadyWait::wait(5500, clock, [&]() { return ready; },
        [&](uint32_t) {
            ++blocks;
            now += 100;
            if (blocks == 2) ready = true;
        });
    check(result.ready && result.elapsedUs == 200 && blocks == 2,
          "spurious notification does not report a successful conversion");

    blocks = 0;
    result = AdcReadyWait::wait(5500, clock, []() { return false; },
        [&](uint32_t remainingUs) { ++blocks; now += remainingUs; });
    check(!result.ready && result.elapsedUs == 5500 && blocks == 1,
          "missing DRDY terminates at the bounded timeout");

    ready = false;
    result = AdcReadyWait::wait(5500, clock, [&]() { return ready; },
        [&](uint32_t remainingUs) { now += remainingUs + 500; ready = true; });
    check(result.ready && result.elapsedUs == 6000,
          "level is checked after rounded timeout even if an edge was missed");

    now = UINT32_MAX - 100;
    result = AdcReadyWait::wait(5500, clock, []() { return false; },
        [&](uint32_t remainingUs) { now += remainingUs; });
    check(!result.ready && result.elapsedUs == 5500,
          "micros wraparound preserves the timeout");
    check(AdcReadyWait::timeoutTicks(1, 1000) == 1 &&
              AdcReadyWait::timeoutTicks(500, 1000) == 1 &&
              AdcReadyWait::timeoutTicks(5500, 1000) == 6 &&
              AdcReadyWait::timeoutTicks(1000, 1000) == 1 &&
              AdcReadyWait::timeoutTicks(5500, 100) == 1,
          "positive notification timeouts round up at different RTOS tick rates");

    std::printf("ADC ready wait: %d passed, %d failed\n", passed, failed);
    return failed;
}
