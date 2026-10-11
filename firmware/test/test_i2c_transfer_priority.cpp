#include <cstdio>
#include <type_traits>

#include "I2CTransferPriority.h"

namespace {
struct FakeTasks {
  static inline bool worker = true;
  static inline unsigned currentPriority = 1;
  static inline unsigned changes = 0;
  static bool eligible() { return worker; }
  static unsigned priority() { return currentPriority; }
  static void setPriority(unsigned value) {
    currentPriority = value;
    ++changes;
  }
  static void reset(unsigned value = 1, bool eligible = true) {
    worker = eligible;
    currentPriority = value;
    changes = 0;
  }
};
using Scope = I2CTransferPriority::Scope<FakeTasks>;
static_assert(!std::is_copy_constructible_v<Scope>);
static_assert(!std::is_copy_assignable_v<Scope>);
} // namespace

int runI2CTransferPriorityTests() {
  int passed = 0;
  int failed = 0;
#define CHECK_PRIORITY(condition) do { \
  if (condition) ++passed; \
  else { ++failed; std::printf("FAIL: priority line %d: %s\n", __LINE__, #condition); } \
} while (0)

  FakeTasks::reset();
  {
    Scope transfer(2);
    CHECK_PRIORITY(FakeTasks::currentPriority == 2);
  }
  CHECK_PRIORITY(FakeTasks::currentPriority == 1 && FakeTasks::changes == 2);

  // The short-read/error return must restore priority before the caller parses
  // or retries, just as the successful path does.
  FakeTasks::reset();
  const auto failedRead = [&]() {
    Scope transfer(2);
    CHECK_PRIORITY(FakeTasks::currentPriority == 2);
    return false;
  };
  CHECK_PRIORITY(!failedRead());
  CHECK_PRIORITY(FakeTasks::currentPriority == 1 && FakeTasks::changes == 2);

  FakeTasks::reset();
  {
    Scope fastRead(2);
    {
      Scope fallbackRead(2);
      CHECK_PRIORITY(FakeTasks::currentPriority == 2 && FakeTasks::changes == 1);
    }
    CHECK_PRIORITY(FakeTasks::currentPriority == 2 && FakeTasks::changes == 1);
  }
  CHECK_PRIORITY(FakeTasks::currentPriority == 1 && FakeTasks::changes == 2);

  FakeTasks::reset(3);
  { Scope transfer(2); }
  CHECK_PRIORITY(FakeTasks::currentPriority == 3 && FakeTasks::changes == 0);

  FakeTasks::reset(1, false);
  { Scope transfer(2); }
  CHECK_PRIORITY(FakeTasks::currentPriority == 1 && FakeTasks::changes == 0);

  FakeTasks::reset();
  { Scope disabled(0); }
  CHECK_PRIORITY(FakeTasks::currentPriority == 1 && FakeTasks::changes == 0);

#undef CHECK_PRIORITY
  std::printf("I2C transfer priority: %d passed, %d failed\n", passed, failed);
  return failed;
}
