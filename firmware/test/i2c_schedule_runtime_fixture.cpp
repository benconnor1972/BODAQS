// Production selections and the actual BMI270 yield limit are inserted by
// tools/test_i2c_schedule_runtime.py. The fixture supplies clients and time.
#include <atomic>
#include <cstdint>
#include <cstdio>
#include "I2CSchedulePlan.h"

struct I2CAsyncClient {
  bool sensitive = false, muted = false;
  uint8_t bus = 1;
  uint32_t estimate = 12000, gap = 70000;
  virtual ~I2CAsyncClient() = default;
  virtual uint8_t asyncMaximumLatencySensitiveYields() const { return 0; }
  bool asyncLatencySensitive() const { return sensitive; }
  bool asyncMuted() const { return muted; }
  uint8_t asyncI2CBusIndex() const { return bus; }
  uint32_t asyncEstimatedAcquireUs() const { return estimate; }
  uint32_t asyncMaximumLowPriorityGapUs() const { return gap; }
};
struct BufferedClient : I2CAsyncClient {
  // PRODUCTION_YIELD_LIMIT
};
struct ClientSlot {
  I2CAsyncClient* client = nullptr;
  bool registered = false;
  uint64_t nextDueUs = 0;
  uint8_t priorityYieldCountForCurrentService = 0;
  uint32_t priorityDeferralCount = 0, priorityServiceCount = 0;
};
constexpr uint8_t kMaxClients = 4, kMaxBuses = 2;
constexpr uint32_t kMutedClientBackoffUs = 250000;
ClientSlot s_clients[kMaxClients];
std::atomic<uint32_t> s_lastSuccessfulAcquireEndUs[kMaxClients];
uint8_t s_nextTieStart[kMaxBuses]{};
uint32_t clockUs = 50000;
uint32_t micros() { return clockUs; }

// PRODUCTION_SELECTION

unsigned checks = 0, failures = 0;
void check(bool condition, const char* message) {
  ++checks;
  if (!condition) { ++failures; std::printf("FAIL scheduler: %s\n", message); }
}
int main() {
  BufferedClient fifo, otherFifo;
  I2CAsyncClient angle, otherAngle;
  angle.sensitive = otherAngle.sensitive = true;
  angle.estimate = otherAngle.estimate = 1000;
  auto reset = [&]() {
    fifo = BufferedClient{}; otherFifo = BufferedClient{};
    angle.muted = otherAngle.muted = false;
    angle.bus = otherAngle.bus = 1;
    angle.estimate = otherAngle.estimate = 1000;
    clockUs = 50000;
    for (uint8_t i = 0; i < kMaxClients; ++i) {
      s_clients[i] = ClientSlot{};
      s_lastSuccessfulAcquireEndUs[i].store(0);
    }
    s_clients[0] = {&fifo, true, 40000};
    s_clients[1] = {&angle, true, 51000};
    s_clients[2] = {&otherFifo, true, 41000};
    s_lastSuccessfulAcquireEndUs[0].store(10000);
    s_nextTieStart[1] = 0;
  };
  uint64_t service = 0, earliest = 0;
  auto choose = [&]() { return latencySensitiveClientBeforeBlock_(1, s_clients[0], clockUs, service); };
  reset();
  check(fifo.asyncMaximumLatencySensitiveYields() == 2, "BMI270 has two-yield limit");
  check(nextDueClient_(1, clockUs, earliest) == &s_clients[0], "oldest FIFO selected");
  check(choose() == &s_clients[1] && service == 51000, "first deadline look-ahead yields to angle");
  clockUs = 52000; s_clients[1].nextDueUs = 53000;
  check(choose() == &s_clients[1] && service == 53000, "second yield allowed");
  clockUs = 54000; s_clients[1].nextDueUs = 55000;
  check(choose() == nullptr, "third yield refused even though FIFO has capacity");
  check(s_clients[0].priorityYieldCountForCurrentService == 2 &&
        s_clients[0].priorityDeferralCount == 2 && s_clients[1].priorityServiceCount == 2,
        "only admitted yields update counters");
  check(nextDueClient_(1, clockUs, earliest) == &s_clients[0], "FIFO still selected after two yields");
  reset(); s_lastSuccessfulAcquireEndUs[0].store(0);
  check(choose() == nullptr, "no deferral before first successful FIFO service");
  reset(); s_clients[1].nextDueUs = 62001;
  check(choose() == nullptr, "deadline outside FIFO burst does not justify deferral");
  reset(); s_clients[1].nextDueUs = 62000;
  check(choose() == &s_clients[1], "deadline at FIFO burst end is eligible");
  reset(); clockUs = 79000;
  check(choose() == &s_clients[1], "projected start at maximum age is admitted");
  reset(); clockUs = 79001;
  check(choose() == nullptr, "projected start beyond maximum age is refused");
  reset(); angle.muted = true;
  check(choose() == nullptr, "muted angle cannot defer FIFO");
  reset(); angle.bus = 0;
  check(choose() == nullptr, "different bus cannot defer FIFO");
  reset(); angle.estimate = 0;
  check(choose() == nullptr, "unknown angle duration cannot justify deferral");
  reset(); fifo.estimate = 0;
  check(choose() == nullptr, "unknown FIFO duration prevents deferral");
  reset(); fifo.gap = 0;
  check(choose() == nullptr, "missing gap budget prevents deferral");
  reset(); fifo.sensitive = true;
  check(choose() == nullptr, "latency-sensitive client is not displaced by this policy");
  reset(); s_clients[3] = {&otherAngle, true, 50500};
  check(choose() == &s_clients[3] && service == 50500, "earliest eligible angle wins");
  reset(); s_clients[1].nextDueUs = 49000;
  check(choose() == &s_clients[1] && service == clockUs, "overdue angle serviced immediately");
  reset(); s_clients[1].registered = false;
  check(choose() == nullptr, "unregistered angle ignored");
  reset(); angle.muted = true;
  check(nextDueClient_(1, clockUs, earliest) == &s_clients[0] &&
        s_clients[1].nextDueUs == clockUs + kMutedClientBackoffUs, "muted client backs off");
  reset(); s_clients[0].nextDueUs = s_clients[2].nextDueUs = 40000;
  s_nextTieStart[1] = 2;
  check(nextDueClient_(1, clockUs, earliest) == &s_clients[2], "rotating cursor breaks equal-deadline ties");
  reset(); clockUs = 32; s_lastSuccessfulAcquireEndUs[0].store(UINT32_MAX - 100);
  s_clients[1].nextDueUs = 33;
  check(choose() == &s_clients[1], "32-bit service-age calculation survives timer wrap");
  std::printf("Two-deferral production scheduler: %u checks, %u failures\n", checks, failures);
  return failures ? 1 : 0;
}
