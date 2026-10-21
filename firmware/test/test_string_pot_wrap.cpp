#include <cstdio>
#include "StringPotWrapTracker.h"

int runStringPotWrapTests() {
  int failed = 0;
  auto check = [&](bool condition, const char* description) {
    if (!condition) {
      std::printf("    FAIL: string pot wrap: %s\n", description);
      ++failed;
    }
  };
  StringPotWrapTracker tracker;
  auto step = [&](int raw) { return tracker.update(raw, 4096, 2048, true); };

  // Session 261019_153445_d1d69224e898, 4.532--4.538 s.
  tracker.reset(4079, 4079, 4096);
  check(step(2054) == 4079, "hold midscale settling sample");
  check(step(38) == 4134, "count forward wrap despite two sub-threshold steps");
  check(step(97) == 4193, "retain the corrected turn on subsequent movement");

  // Same recording, reverse crossing at 6.490--6.494 s.
  tracker.reset(10, 4106, 4096);
  check(step(2040) == 4106, "hold reverse settling sample");
  check(step(4064) == 4064, "count reverse wrap despite two sub-threshold steps");

  tracker.reset(4079, 4079, 4096);
  check(step(38) == 4134 && step(4079) == 4079,
        "direct wraps and immediate reversal count once each");

  tracker.reset(4079, 4079, 4096);
  check(step(3000) == 4079 && step(2054) == 4079 && step(1000) == 4079 &&
            step(38) == 4134, "allow up to three intermediate samples");

  tracker.reset(4079, 4079, 4096);
  check(step(2054) == 4079 && step(2054) == 4079 && step(2054) == 4079 &&
            step(2054) == 2054 && step(2055) == 2055,
        "a stationary midscale signal expires the hold and resumes tracking");

  tracker.reset(4079, 4079, 4096);
  check(step(2054) == 4079 && step(4070) == 4070 && step(38) == 4134,
        "an excursion returning to the same edge does not add a turn");

  tracker.reset(0, 0, 4096);
  bool rampOk = true;
  for (int raw = 100; raw < 4096; raw += 100) rampOk &= step(raw) == raw;
  for (int raw = 4000; raw >= 0; raw -= 100) rampOk &= step(raw) == raw;
  check(rampOk, "ordinary full-range movement in either direction is unchanged");

  tracker.reset(100, -3996, 4096);
  check(step(90) == -4006, "negative turn offsets are retained");
  tracker.reset(4079, 4079, 4096);
  (void)step(2054);
  tracker.reset(1000, 1000, 4096);
  check(step(1100) == 1100, "reset clears pending transitions and turn history");

  tracker.reset(4079, 4079, 4096);
  check(tracker.update(2054, 4096, 2048, false) == 2054,
        "I2C samples retain the existing consecutive-sample behavior");
  tracker.reset(4000, 4000, 4096);
  check(tracker.update(1000, 4096, 3000, false) == 5096,
        "configured threshold remains inclusive");
  tracker.reset(1010, 1010, 1024);
  check(tracker.update(515, 1024, 512, true) == 1010 &&
            tracker.update(10, 1024, 512, true) == 1034,
        "analog detection scales with configured counts per turn");
  std::printf("String pot wrap tests: %d failed\n", failed);
  return failed;
}
