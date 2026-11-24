#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <sys/time.h>
#include <vector>
#include "BoardProfile.h"
#include "RTCManager.h"

#define RTC_LOGI(...) ((void)0)
#define RTC_LOGW(...) ((void)0)
constexpr int INPUT = 0, INPUT_PULLUP = 1;
void pinMode(uint8_t, int) {}
time_t systemEpoch = 0;
time_t fakeTime(time_t* out) { if (out) *out = systemEpoch; return systemEpoch; }
#define time fakeTime
int fakeSettimeofday(const timeval* tv, void*) { systemEpoch = tv->tv_sec; return 0; }
#define settimeofday fakeSettimeofday
#ifdef _WIN32
struct tm* gmtime_r(const time_t* epoch, struct tm* out) {
  return gmtime_s(out, epoch) == 0 ? out : nullptr;
}
#endif
void sntpTimeSyncNotification_(timeval*) {}
void esp_sntp_set_time_sync_notification_cb(void (*)(timeval*)) {}

struct Device {
  bool present = false;
  std::array<uint8_t, 128> regs {};
  int failReadReg = -1, failWriteReg = -1;
  bool shortRead = false, ignoreCalendar = false;
  unsigned writes = 0, reads = 0;
};

struct TwoWire {
  std::array<Device, 128> devices {};
  std::vector<uint8_t> tx, rx;
  uint8_t address = 0, reg = 0;
  size_t readIndex = 0;
  bool held = false, lockOk = true;

  void beginTransmission(uint8_t addr) { assert(held); address = addr; tx.clear(); }
  size_t write(uint8_t byte) { tx.push_back(byte); return 1; }
  uint8_t endTransmission(bool stop = true) {
    assert(held && !tx.empty());
    auto& d = devices[address];
    if (!d.present) return 2;
    reg = tx[0];
    if (tx.size() == 1) return reg == d.failReadReg ? 4 : 0;
    assert(stop);
    ++d.writes;
    if (reg == d.failWriteReg) return 4;
    if (address == 0x6F) {
      // ISL1208 transactions may not cross a register section boundary.
      assert((reg == 0 && tx.size() == 8) || (reg == 7 && tx.size() == 2));
      if (reg == 0) {
        if (!(d.regs[7] & 0x10) || d.ignoreCalendar) return 0;
        d.regs[7] &= (uint8_t)~1; // RTCF clears only on a valid calendar write
      } else {
        // RTCF is read-only; BAT/ALM cannot be set by software.
        d.regs[7] = (tx[1] & 0xD0) | (d.regs[7] & tx[1] & 0x06) | (d.regs[7] & 1);
        return 0;
      }
    }
    for (size_t i = 1; i < tx.size(); ++i) d.regs[reg + i - 1] = tx[i];
    return 0;
  }
  size_t requestFrom(int addr, int len) {
    assert(held && addr == address);
    auto& d = devices[address];
    if (addr == 0x6F) assert((reg == 0 && len == 7) || (reg == 7 && len == 1));
    ++d.reads;
    rx.clear(); readIndex = 0;
    if (d.shortRead) --len;
    for (int i = 0; i < len; ++i) rx.push_back(d.regs[reg + i]);
    return rx.size();
  }
  int read() { assert(readIndex < rx.size()); return rx[readIndex++]; }
};
TwoWire wire;
namespace I2CManager {
bool busAvailable = true;
TwoWire* bus(uint8_t index) { return index == 0 && busAvailable ? &wire : nullptr; }
bool lock(TwoWire* w) { assert(!w->held); return w->held = w->lockOk; }
void unlock(TwoWire* w) { assert(w->held); w->held = false; }
}

// PRODUCTION_RTC

constexpr time_t leapEpoch = 1709210096; // 2024-02-29 12:34:56 UTC
const std::array<uint8_t, 7> islLeap = {0x56, 0x34, 0x92, 0x29, 0x02, 0x24, 4};
const std::array<uint8_t, 7> rvLeap = {0x56, 0x34, 0x12, 4, 0x29, 0x02, 0x24};

void reset() {
  wire = TwoWire{};
  I2CManager::busAvailable = true;
  baseEpoch = 0; systemEpoch = 0;
  RTCManager_begin(RTC_INTERNAL);
}
Device& addIsl(bool lost = false) {
  auto& d = wire.devices[0x6F];
  d.present = true;
  std::copy(islLeap.begin(), islLeap.end(), d.regs.begin());
  d.regs[7] = lost ? 1 : 0;
  if (lost) std::fill_n(d.regs.begin(), 7, 0); // actual power-on calendar
  return d;
}
Device& addRv(bool lost = false) {
  auto& d = wire.devices[0x52];
  d.present = true;
  std::copy(rvLeap.begin(), rvLeap.end(), d.regs.begin());
  d.regs[0x0E] = lost ? 1 : 0;
  d.regs[0x37] = 0x0C; // backup already configured; detection must not write
  return d;
}
board::RtcProfile autoProfile() {
  board::RtcProfile p;
  p.type = board::RtcType::Auto;
  p.i2c_addr = 0;
  return p;
}
void expectInternal() {
  assert(!RTCManager_usingExternalRtc());
  assert(!RTCManager_externalRtcLastReadOk());
  assert(!RTCManager_externalRtcPorf());
  assert(std::strcmp(RTCManager_sourceLabel(), "internal") == 0);
  assert(!wire.held);
}

int main() {
  reset();
  auto& rv = addRv();
  RTCManager_begin(autoProfile());
  assert(RTCManager_usingExternalRtc() && RTCManager_externalRtcLastReadOk());
  assert(std::strcmp(RTCManager_sourceLabel(), "RV3028") == 0);
  assert(systemEpoch == leapEpoch && rv.writes == 0);
  assert(s_externalRtcProfile.i2c_addr == 0x52);
  assert(externalRtcWriteEpoch_(leapEpoch));
  assert(std::equal(rvLeap.begin(), rvLeap.end(), rv.regs.begin()));
  // Existing battery configuration repair still runs after RV detection.
  reset();
  auto& backup = addRv();
  backup.regs[0x37] = 0xA1; // calibration bit + trickle charging, no backup switching
  RTCManager_begin(autoProfile());
  assert(backup.regs[0x37] == 0x8D && backup.writes > 0);
  assert(wire.devices[0x6F].writes == 0);

  reset();
  auto& isl = addIsl();
  RTCManager_begin(autoProfile());
  assert(RTCManager_usingExternalRtc() && RTCManager_externalRtcLastReadOk());
  assert(std::strcmp(RTCManager_sourceLabel(), "ISL1208") == 0);
  assert(s_externalRtcProfile.i2c_addr == 0x6F);
  assert(systemEpoch == leapEpoch && isl.writes == 0);
  assert(wire.devices[0x52].writes == 0);
  // A failed read retains the cached epoch and releases the bus.
  isl.shortRead = true;
  RTCManager_sync();
  assert(!RTCManager_externalRtcLastReadOk() && baseEpoch == leapEpoch && !wire.held);

  // Neither, both, unavailable bus and lock failure all fail without writes.
  reset(); RTCManager_begin(autoProfile()); expectInternal();
  reset(); addRv(); addIsl(); RTCManager_begin(autoProfile()); expectInternal();
  assert(wire.devices[0x52].writes == 0 && wire.devices[0x6F].writes == 0);
  reset(); addIsl(); I2CManager::busAvailable = false;
  RTCManager_begin(autoProfile()); expectInternal();
  reset(); addIsl(); wire.lockOk = false;
  RTCManager_begin(autoProfile()); expectInternal();
  reset(); addIsl().shortRead = true;
  RTCManager_begin(autoProfile()); expectInternal();
  reset(); addIsl().regs[7] = 0xFF;
  RTCManager_begin(autoProfile()); expectInternal();
  reset(); addRv().regs[2] = 0xFF;
  RTCManager_begin(autoProfile()); expectInternal();

  // Detection must accept power-loss states even though time is untrusted.
  reset(); addRv(true); RTCManager_begin(autoProfile());
  assert(RTCManager_usingExternalRtc() && RTCManager_externalRtcPorf());
  assert(!RTCManager_externalRtcLastReadOk() && baseEpoch == 0);
  assert(externalRtcWriteEpoch_(leapEpoch));
  RTCManager_sync();
  assert(RTCManager_externalRtcLastReadOk() && !RTCManager_externalRtcPorf());
  reset();
  auto& unset = addIsl(true);
  RTCManager_begin(autoProfile());
  assert(RTCManager_usingExternalRtc() && RTCManager_externalRtcPorf());
  assert(!RTCManager_externalRtcLastReadOk() && unset.writes == 0);
  unset.regs[7] |= 0x46; // oscillator disabled, battery/alarm flags set
  unset.regs[0x0A] = 0x25; unset.regs[0x0B] = 3; // calibrated device
  assert(externalRtcWriteEpoch_(leapEpoch));
  assert(std::equal(islLeap.begin(), islLeap.end(), unset.regs.begin()));
  assert(unset.regs[7] == 0x06); // WRTC re-locked, RTCF cleared, crystal enabled
  assert(unset.regs[0x0A] == 0x25 && unset.regs[0x0B] == 3);
  RTCManager_sync();
  assert(systemEpoch == leapEpoch && RTCManager_externalRtcLastReadOk());
  assert(!RTCManager_externalRtcPorf());

  // Known UTC values exercise 12-hour midnight, noon, PM and 24-hour midnight.
  for (auto hour : {0x12, 0x32, 0x21, 0x80}) {
    reset(); auto& d = addIsl(); d.regs[2] = hour;
    RTCManager_begin(autoProfile());
    assert(RTCManager_externalRtcLastReadOk());
    const time_t start = 1709164800; // 2024-02-29 00:00:00 UTC
    const int hours = hour == 0x32 ? 12 : hour == 0x21 ? 13 : 0;
    assert(systemEpoch == start + hours * 3600 + 34 * 60 + 56);
  }
  // Invalid BCD, calendar dates, weekday, stopped oscillator, old time.
  for (auto scenario : {0, 1, 2, 3, 4, 5, 6, 7}) {
    reset(); auto& d = addIsl();
    if (scenario == 0) d.regs[0] = 0x5A;
    if (scenario == 1) d.regs[3] = 0x30; // February 30
    if (scenario == 2) d.regs[6] = 7;
    if (scenario == 3) d.regs[7] = 0x40;
    if (scenario == 4) d.regs[5] = 0x19;
    if (scenario == 5) d.regs[2] = 0x00; // invalid 12-hour value
    if (scenario == 6) d.regs[1] = 0x60;
    if (scenario == 7) d.regs[2] = 0xA4; // 24:xx in 24-hour mode
    RTCManager_begin(autoProfile());
    assert(RTCManager_usingExternalRtc() && !RTCManager_externalRtcLastReadOk());
    assert(baseEpoch == 0 && d.writes == 0);
  }
  // Re-protect after failed calendar transfer and reject silently ignored writes.
  reset(); auto& failed = addIsl(true); RTCManager_begin(autoProfile());
  failed.failWriteReg = 0;
  assert(!externalRtcWriteEpoch_(leapEpoch));
  assert(!(failed.regs[7] & 0x10) && RTCManager_externalRtcPorf() && !wire.held);
  failed.failWriteReg = -1; failed.ignoreCalendar = true;
  assert(!externalRtcWriteEpoch_(leapEpoch) && RTCManager_externalRtcPorf());
  assert(!(failed.regs[7] & 0x10));
  assert(!externalRtcWriteEpoch_(0));
  assert(!externalRtcWriteEpoch_(4102444800LL)); // 2100, outside chip range

  // Explicit profiles never scan/select a different chip; None disables probing.
  reset(); addRv(); addIsl();
  board::RtcProfile explicitRtc;
  explicitRtc.type = board::RtcType::RV3028;
  RTCManager_begin(explicitRtc);
  assert(std::strcmp(RTCManager_sourceLabel(), "RV3028") == 0);
  assert(wire.devices[0x6F].reads == 0);
  explicitRtc.type = board::RtcType::ISL1208; explicitRtc.i2c_addr = 0x6F;
  RTCManager_begin(explicitRtc);
  assert(std::strcmp(RTCManager_sourceLabel(), "ISL1208") == 0);
  RTCManager_begin(board::RtcProfile{}); expectInternal();
  std::puts("RTC runtime: detection, UTC calendars, power loss, write protection and I2C faults passed");
}
