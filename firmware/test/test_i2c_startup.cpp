#include <cstdio>
#include "I2CStartupRecovery.h"

namespace {
struct FakeOps {
  uint8_t sensors = 3;
  bool safeToRun = true;
  bool didAbort = false;
  bool diagnosticRetryAllowedRecovery = false;
  bool initialReady[3] {true, false, false};
  bool ready[3] {true, false, false};
  uint8_t buses[3] {1, 1, 1};
  int succeedsAt[3] {-1, 1, 2};
  bool restartOk = true;
  bool slowOk = true;
  bool restoreOk = true;
  unsigned retries[3] {};
  unsigned probes[3] {};
  unsigned resets[2] {};
  unsigned slow[2] {};
  unsigned restores[2] {};
  unsigned waited = 0;
  unsigned snapshots = 0;
  unsigned remaining = 255;
  uint8_t count() { return sensors; }
  bool safe() { return safeToRun; }
  void aborted() { didAbort = true; }
  bool describe(uint8_t i, I2CStartupStatus& s) {
    s.busIndex = buses[i]; s.ready = ready[i]; return true;
  }
  void snapshot(uint8_t i, const I2CStartupStatus& s) {
    initialReady[i] = s.ready; ++snapshots;
  }
  void wait(uint32_t ms) { waited += ms; }
  bool restart(uint8_t bus) { ++resets[bus]; return restartOk; }
  bool slowClock(uint8_t bus) { ++slow[bus]; return slowOk; }
  void restoreClock(uint8_t bus) {
    ++restores[bus];
    if (!restoreOk) {
      for (uint8_t i = 0; i < 3; ++i) if (buses[i] == bus) ready[i] = false;
    }
  }
  bool probe(uint8_t i, I2CStartupRecovery::Phase) { ++probes[i]; return true; }
  bool retry(uint8_t i, I2CStartupRecovery::Phase phase, bool allowRecovery) {
    ++retries[i]; diagnosticRetryAllowedRecovery |= allowRecovery;
    ready[i] = static_cast<int>(phase) == succeedsAt[i]; return ready[i];
  }
  void finished(uint8_t count) { remaining = count; }
};
}

int runI2CStartupTests() {
  int passed = 0, failed = 0;
#define CHECK_STARTUP(c) do { if (c) ++passed; else { ++failed; std::printf("FAIL startup line %d: %s\n", __LINE__, #c); } } while (0)
  FakeOps ops;
  I2CStartupRecovery::run(ops, true);
  CHECK_STARTUP(ops.remaining == 0);
  CHECK_STARTUP(ops.retries[0] == 0 && ops.probes[0] == 0);
  CHECK_STARTUP(ops.retries[1] == 2 && ops.retries[2] == 3);
  CHECK_STARTUP(ops.resets[1] == 1 && ops.slow[1] == 1 && ops.restores[1] == 1);
  CHECK_STARTUP(!ops.diagnosticRetryAllowedRecovery);
  CHECK_STARTUP(!ops.initialReady[1] && !ops.initialReady[2]);
  CHECK_STARTUP(ops.waited == 250 && ops.snapshots == 3);

  ops = FakeOps{}; ops.succeedsAt[1] = ops.succeedsAt[2] = 0;
  I2CStartupRecovery::run(ops, true);
  CHECK_STARTUP(ops.remaining == 0 && ops.resets[1] == 0 && ops.slow[1] == 0);
  ops = FakeOps{}; ops.succeedsAt[1] = ops.succeedsAt[2] = -1;
  I2CStartupRecovery::run(ops, true);
  CHECK_STARTUP(ops.remaining == 2 && ops.retries[1] == 3 && ops.retries[2] == 3);
  CHECK_STARTUP(ops.restores[1] == 1);
  ops = FakeOps{}; ops.slowOk = false;
  I2CStartupRecovery::run(ops, true);
  CHECK_STARTUP(ops.remaining == 1 && ops.retries[2] == 2 && ops.restores[1] == 1);
  ops = FakeOps{}; ops.restartOk = false;
  I2CStartupRecovery::run(ops, true);
  CHECK_STARTUP(ops.retries[1] == 2 && ops.retries[2] == 2 && ops.remaining == 1);
  ops = FakeOps{}; ops.buses[1] = 0;
  I2CStartupRecovery::run(ops, true);
  CHECK_STARTUP(ops.resets[0] == 1 && ops.resets[1] == 1);
  ops = FakeOps{}; ops.safeToRun = false;
  I2CStartupRecovery::run(ops, true);
  CHECK_STARTUP(ops.didAbort && ops.snapshots == 0 && ops.waited == 0);
  ops = FakeOps{}; ops.sensors = 33;
  I2CStartupRecovery::run(ops, true);
  CHECK_STARTUP(ops.didAbort);
  ops = FakeOps{}; ops.ready[1] = ops.ready[2] = true;
  I2CStartupRecovery::run(ops, true);
  CHECK_STARTUP(ops.waited == 0 && ops.remaining == 0 && ops.resets[1] == 0);
  ops = FakeOps{}; ops.restoreOk = false;
  I2CStartupRecovery::run(ops, true);
  CHECK_STARTUP(ops.remaining == 3 && !ops.ready[0]);
  ops = FakeOps{};
  I2CStartupRecovery::run(ops, false);
  CHECK_STARTUP(ops.probes[1] == 0 && ops.retries[1] == 1 && ops.retries[2] == 1);
  CHECK_STARTUP(ops.resets[1] == 0 && ops.slow[1] == 0 && ops.diagnosticRetryAllowedRecovery);

  unsigned attempts = 0, recoveries = 0, waits = 0;
  auto probe = [&]() { return ++attempts == 4; };
  auto recover = [&]() { ++recoveries; return true; };
  auto wait = [&](uint32_t ms) { waits += ms; };
  CHECK_STARTUP(I2CStartupRecovery::probeWithRetries(probe, recover, wait, true));
  CHECK_STARTUP(attempts == 4 && recoveries == 1 && waits == 20);
  attempts = recoveries = waits = 0;
  CHECK_STARTUP(!I2CStartupRecovery::probeWithRetries(probe, recover, wait, false));
  CHECK_STARTUP(attempts == 3 && recoveries == 0 && waits == 20);
  attempts = recoveries = waits = 0;
  CHECK_STARTUP(!I2CStartupRecovery::probeWithRetries([]() { return false; }, recover, wait, true));
  CHECK_STARTUP(recoveries == 1 && waits == 40);
  attempts = recoveries = waits = 0;
  CHECK_STARTUP(I2CStartupRecovery::probeWithRetries([]() { return true; }, recover, wait, true));
  CHECK_STARTUP(recoveries == 0 && waits == 0);
  std::printf("I2C startup: %d passed, %d failed\n", passed, failed);
  return failed;
}
