#include "AS5048LibraryProbe.h"

#if defined(BODAQS_AS5048_LIBRARY_PROBE)

#include <Arduino.h>
#include <Wire.h>
#include <ams_as5048b.h>
#include <string.h>

#include "I2CManager.h"

#ifndef BODAQS_AS5048_PROBE_BUS
#define BODAQS_AS5048_PROBE_BUS 1
#endif

#ifndef BODAQS_AS5048_PROBE_ADDR
#define BODAQS_AS5048_PROBE_ADDR 0x40
#endif

#ifndef BODAQS_AS5048_PROBE_HZ
#define BODAQS_AS5048_PROBE_HZ 100000UL
#endif

#ifndef BODAQS_AS5048_PROBE_PERIOD_MS
#define BODAQS_AS5048_PROBE_PERIOD_MS 100UL
#endif

#ifndef BODAQS_AS5048_PROBE_MATRIX_ROWS
#define BODAQS_AS5048_PROBE_MATRIX_ROWS 5
#endif

// Default to the datasheet random-read transaction. STOP reads remain useful
// as a comparison path because they have shown byte-pair reversal on ESP32 Wire.
#ifndef BODAQS_AS5048_PROBE_STOP_READS
#define BODAQS_AS5048_PROBE_STOP_READS 0
#endif

namespace {

static constexpr uint8_t kRegAgc = 0xFA;
static constexpr uint8_t kRegAngle = 0xFE;
static constexpr uint8_t kAs5048FirstAddr = 0x40;
static constexpr uint8_t kAs5048LastAddr = 0x43;
static constexpr uint16_t kCountsPerTurn = 16384;
static constexpr uint16_t kHalfTurn = kCountsPerTurn / 2;
static constexpr float kDegreesPerCount = 360.0f / float(kCountsPerTurn);

static constexpr uint8_t kDiagOcf = 0x01;
static constexpr uint8_t kDiagCof = 0x02;
static constexpr uint8_t kDiagCompLow = 0x04;
static constexpr uint8_t kDiagCompHigh = 0x08;

struct ReadResult {
  uint8_t txStatus = 255;
  size_t got = 0;
  uint8_t bytes[6] = {0};
};

struct ValidationSample {
  uint32_t ms = 0;
  uint8_t addr = 0;
  uint8_t ack = 255;
  bool stopAfterReg = true;
  ReadResult angle;
  ReadResult block;
  bool angleOk = false;
  bool blockOk = false;
  bool haveDelta = false;
  int32_t delta = 0;
  uint16_t raw = 0;
  uint16_t blockRaw = 0;
  uint8_t agc = 0;
  uint8_t diag = 0;
  uint16_t mag = 0;
  bool valid = false;
  char flags[128] = {0};
};

static void scanBus_(TwoWire& wire) {
  bool foundAny = false;
  Serial.print("[AS5048-PROBE] scan:");
  for (uint8_t addr = 1; addr < 127; ++addr) {
    wire.beginTransmission(addr);
    const uint8_t err = wire.endTransmission(true);
    if (err == 0) {
      Serial.printf(" 0x%02X", (unsigned)addr);
      foundAny = true;
    }
    delay(1);
  }
  if (!foundAny) Serial.print(" none");
  Serial.println();
}

static uint8_t ping_(TwoWire& wire, uint8_t addr) {
  wire.beginTransmission(addr);
  return wire.endTransmission(true);
}

static ReadResult readFromReg_(TwoWire& wire, uint8_t addr, uint8_t reg, uint8_t len, bool stopAfterReg) {
  ReadResult r;
  wire.beginTransmission(addr);
  wire.write(reg);
  r.txStatus = wire.endTransmission(stopAfterReg);
  if (r.txStatus != 0) return r;

  if (stopAfterReg) delayMicroseconds(5);
  r.got = wire.requestFrom((int)addr, (int)len);
  const size_t n = (r.got < sizeof(r.bytes)) ? r.got : sizeof(r.bytes);
  for (size_t i = 0; i < n; ++i) {
    const int v = wire.read();
    r.bytes[i] = (v < 0) ? 0xFFu : (uint8_t)v;
  }
  return r;
}

static ReadResult readDirect_(TwoWire& wire, uint8_t addr, uint8_t len) {
  ReadResult r;
  r.txStatus = 0;
  r.got = wire.requestFrom((int)addr, (int)len);
  const size_t n = (r.got < sizeof(r.bytes)) ? r.got : sizeof(r.bytes);
  for (size_t i = 0; i < n; ++i) {
    const int v = wire.read();
    r.bytes[i] = (v < 0) ? 0xFFu : (uint8_t)v;
  }
  return r;
}

static uint16_t decode14_(uint8_t msb, uint8_t lsb) {
  return (uint16_t(msb) << 6) | (lsb & 0x3Fu);
}

static uint16_t decode14Swapped_(uint8_t lsb, uint8_t msb) {
  return (uint16_t(msb) << 6) | (lsb & 0x3Fu);
}

static int32_t signedDelta14_(uint16_t current, uint16_t previous) {
  int32_t delta = int32_t(current) - int32_t(previous);
  if (delta > int32_t(kHalfTurn)) delta -= int32_t(kCountsPerTurn);
  if (delta < -int32_t(kHalfTurn)) delta += int32_t(kCountsPerTurn);
  return delta;
}

static void appendFlag_(char* out, size_t cap, const char* flag) {
  if (!out || cap == 0 || !flag || !*flag) return;
  const size_t len = strnlen(out, cap);
  if (len >= cap - 1) return;
  if (len > 0) {
    strncat(out, "|", cap - strlen(out) - 1);
  }
  strncat(out, flag, cap - strlen(out) - 1);
}

static void buildFlags_(ValidationSample& s) {
  s.flags[0] = '\0';

  if (s.ack != 0) appendFlag_(s.flags, sizeof(s.flags), "NO_ACK");
  if (!s.angleOk) appendFlag_(s.flags, sizeof(s.flags), "ANGLE_READ_FAIL");
  if (!s.blockOk) appendFlag_(s.flags, sizeof(s.flags), "BLOCK_READ_FAIL");

  const bool ocfReady = (s.diag & kDiagOcf) != 0;
  const bool cordicOverflow = (s.diag & kDiagCof) != 0;
  const bool magneticHigh = (s.diag & kDiagCompLow) != 0;
  const bool magneticLow = (s.diag & kDiagCompHigh) != 0;
  const bool agcSaturated = (s.agc == 0u || s.agc == 255u);

  if (s.blockOk) {
    if (!ocfReady) appendFlag_(s.flags, sizeof(s.flags), "OCF_NOT_READY");
    if (cordicOverflow) appendFlag_(s.flags, sizeof(s.flags), "COF");
    if (magneticHigh) appendFlag_(s.flags, sizeof(s.flags), "MAG_HIGH");
    if (magneticLow) appendFlag_(s.flags, sizeof(s.flags), "MAG_LOW");
    if (agcSaturated) appendFlag_(s.flags, sizeof(s.flags), "AGC_SAT");
  }

  if (s.angleOk && s.blockOk) {
    const int32_t mismatch = signedDelta14_(s.raw, s.blockRaw);
    if (mismatch > 32 || mismatch < -32) {
      appendFlag_(s.flags, sizeof(s.flags), "ANGLE_BLOCK_MISMATCH");
    }
  }

  s.valid = s.angleOk &&
            s.blockOk &&
            ocfReady &&
            !cordicOverflow &&
            !magneticHigh &&
            !magneticLow;

  if (s.flags[0] == '\0') {
    strncpy(s.flags, "OK", sizeof(s.flags) - 1);
    s.flags[sizeof(s.flags) - 1] = '\0';
  }
}

static void printRead_(const char* label, const ReadResult& r, uint8_t len) {
  Serial.printf(" %s{tx=%u got=%u bytes=",
                label,
                (unsigned)r.txStatus,
                (unsigned)r.got);
  const uint8_t n = (len < sizeof(r.bytes)) ? len : sizeof(r.bytes);
  for (uint8_t i = 0; i < n; ++i) {
    if (i) Serial.print(' ');
    Serial.printf("%02X", (unsigned)r.bytes[i]);
  }
  Serial.print('}');
}

static ValidationSample readValidationSample_(TwoWire& wire,
                                              uint8_t addr,
                                              bool stopAfterReg,
                                              bool& havePreviousRaw,
                                              uint16_t& previousRaw) {
  ValidationSample s;
  s.ms = millis();
  s.addr = addr;
  s.stopAfterReg = stopAfterReg;
  s.ack = ping_(wire, addr);
  s.angle = readFromReg_(wire, addr, kRegAngle, 2, stopAfterReg);
  s.block = readFromReg_(wire, addr, kRegAgc, 6, stopAfterReg);
  s.angleOk = (s.angle.txStatus == 0 && s.angle.got == 2);
  s.blockOk = (s.block.txStatus == 0 && s.block.got == 6);

  if (s.angleOk) {
    s.raw = stopAfterReg
      ? decode14Swapped_(s.angle.bytes[0], s.angle.bytes[1])
      : decode14_(s.angle.bytes[0], s.angle.bytes[1]);
  }
  if (s.blockOk) {
    s.agc = s.block.bytes[0];
    s.diag = s.block.bytes[1];
    s.mag = stopAfterReg
      ? decode14Swapped_(s.block.bytes[2], s.block.bytes[3])
      : decode14_(s.block.bytes[2], s.block.bytes[3]);
    s.blockRaw = stopAfterReg
      ? decode14Swapped_(s.block.bytes[4], s.block.bytes[5])
      : decode14_(s.block.bytes[4], s.block.bytes[5]);
    if (!s.angleOk) {
      s.raw = s.blockRaw;
    }
  }

  if (s.angleOk || s.blockOk) {
    if (havePreviousRaw) {
      s.delta = signedDelta14_(s.raw, previousRaw);
      s.haveDelta = true;
    }
    previousRaw = s.raw;
    havePreviousRaw = true;
  }

  buildFlags_(s);
  return s;
}

static void printValidationHeader_() {
  Serial.println("[AS5048-PROBE] validation stream: copy rows from the CSV header onward");
  Serial.println("kind,ms,addr,ack,mode,angle_ok,raw,deg,have_delta,delta,agc,diag,diag_hex,mag,valid,flags,angle_tx,angle_got,block_tx,block_got,block_raw,b0,b1,b2,b3,b4,b5");
}

static void printValidationRow_(const ValidationSample& s) {
  const float deg = float(s.raw) * kDegreesPerCount;
  Serial.printf("AS5048,%lu,0x%02X,%u,%s,%u,%u,%.3f,%u,%ld,%u,%u,0x%02X,%u,%u,\"%s\",%u,%u,%u,%u,%u,%02X,%02X,%02X,%02X,%02X,%02X\n",
                (unsigned long)s.ms,
                (unsigned)s.addr,
                (unsigned)s.ack,
                s.stopAfterReg ? "stop" : "repeated",
                s.angleOk ? 1u : 0u,
                (unsigned)s.raw,
                (double)deg,
                s.haveDelta ? 1u : 0u,
                (long)s.delta,
                (unsigned)s.agc,
                (unsigned)s.diag,
                (unsigned)s.diag,
                (unsigned)s.mag,
                s.valid ? 1u : 0u,
                s.flags,
                (unsigned)s.angle.txStatus,
                (unsigned)s.angle.got,
                (unsigned)s.block.txStatus,
                (unsigned)s.block.got,
                (unsigned)s.blockRaw,
                (unsigned)s.block.bytes[0],
                (unsigned)s.block.bytes[1],
                (unsigned)s.block.bytes[2],
                (unsigned)s.block.bytes[3],
                (unsigned)s.block.bytes[4],
                (unsigned)s.block.bytes[5]);
}

} // namespace

void RunAS5048LibraryProbe(const board::BoardProfile& bp) {
  const uint8_t busIndex = (uint8_t)BODAQS_AS5048_PROBE_BUS;
  const uint8_t addr = (uint8_t)BODAQS_AS5048_PROBE_ADDR;

  Serial.println();
  Serial.println("[AS5048-PROBE] sosandroid/AMS_AS5048B direct library probe");

  if (busIndex >= bp.i2c_count || busIndex >= board::BOARD_MAX_I2C_BUSES ||
      !bp.i2c[busIndex].present) {
    Serial.printf("[AS5048-PROBE] board profile has no present I2C bus %u\n",
                  (unsigned)busIndex);
    while (true) delay(1000);
  }

  const auto& i2c = bp.i2c[busIndex];
  if (i2c.sda < 0 || i2c.scl < 0) {
    Serial.printf("[AS5048-PROBE] invalid I2C%u pins: SDA=%d SCL=%d\n",
                  (unsigned)busIndex,
                  (int)i2c.sda,
                  (int)i2c.scl);
    while (true) delay(1000);
  }

  Serial.printf("[AS5048-PROBE] board=%s physical_i2c%u SDA=%d SCL=%d addr=0x%02X hz=%lu\n",
                bp.name,
                (unsigned)busIndex,
                (int)i2c.sda,
                (int)i2c.scl,
                (unsigned)addr,
                (unsigned long)BODAQS_AS5048_PROBE_HZ);

  I2CManager::begin(bp);
  TwoWire* probeWirePtr = I2CManager::bus(busIndex);
  if (!probeWirePtr) {
    Serial.printf("[AS5048-PROBE] I2CManager bus %u unavailable\n",
                  (unsigned)busIndex);
    while (true) delay(1000);
  }

  TwoWire& probeWire = *probeWirePtr;
  Serial.printf("[AS5048-PROBE] matrix_bus=I2CManager bus%u\n",
                (unsigned)busIndex);

  probeWire.setClock((uint32_t)BODAQS_AS5048_PROBE_HZ);
  probeWire.setTimeOut(20);
  delay(20);

  scanBus_(probeWire);
  const uint8_t probeErr = ping_(probeWire, addr);
  Serial.printf("[AS5048-PROBE] address 0x%02X ping result=%u\n",
                (unsigned)addr,
                (unsigned)probeErr);

  uint8_t activeAddr = addr;
  bool haveActiveAddr = (probeErr == 0);
  Serial.print("[AS5048-PROBE] AS5048B candidates:");
  for (uint8_t candidate = kAs5048FirstAddr; candidate <= kAs5048LastAddr; ++candidate) {
    const uint8_t err = ping_(probeWire, candidate);
    Serial.printf(" 0x%02X=%u", (unsigned)candidate, (unsigned)err);
    if (!haveActiveAddr && err == 0) {
      activeAddr = candidate;
      haveActiveAddr = true;
    }
  }
  Serial.println();
  if (activeAddr != addr) {
    Serial.printf("[AS5048-PROBE] using detected address 0x%02X instead of configured 0x%02X\n",
                  (unsigned)activeAddr,
                  (unsigned)addr);
  }
  if (!haveActiveAddr) {
    Serial.println("[AS5048-PROBE] no AS5048B candidate ACKed; validation stream will show read failures");
  }
  Serial.println("[AS5048-PROBE] matrix columns: tx=endTransmission status, got=requestFrom byte count");

  if (busIndex == 0) {
    AMS_AS5048B sensor(activeAddr);
    const uint16_t libraryRaw = sensor.angleRegR();
    Serial.printf("[AS5048-PROBE] library_once raw=%u\n", (unsigned)libraryRaw);
  } else {
    Serial.println("[AS5048-PROBE] library_once skipped: AMS_AS5048B hardcodes global Wire, not Wire1");
  }

  const uint8_t matrixRows = (uint8_t)BODAQS_AS5048_PROBE_MATRIX_ROWS;
  for (uint8_t row = 0; row < matrixRows; ++row) {
    const ReadResult angleRepeated = readFromReg_(probeWire, activeAddr, kRegAngle, 2, false);
    const ReadResult angleStop = readFromReg_(probeWire, activeAddr, kRegAngle, 2, true);
    const ReadResult blockStop = readFromReg_(probeWire, activeAddr, kRegAgc, 6, true);
    const ReadResult direct2 = readDirect_(probeWire, activeAddr, 2);

    const uint16_t repRaw = decode14_(angleRepeated.bytes[0], angleRepeated.bytes[1]);
    const uint16_t stopRaw = decode14_(angleStop.bytes[0], angleStop.bytes[1]);
    const uint16_t stopSwapRaw = decode14Swapped_(angleStop.bytes[0], angleStop.bytes[1]);
    const float repDeg = (float(repRaw) * 360.0f) / 16384.0f;
    const float stopDeg = (float(stopRaw) * 360.0f) / 16384.0f;
    const float stopSwapDeg = (float(stopSwapRaw) * 360.0f) / 16384.0f;

    Serial.printf("[AS5048-PROBE] %lu addr=0x%02X rep_raw=%u rep_deg=%.3f stop_raw=%u stop_deg=%.3f stop_swap_raw=%u stop_swap_deg=%.3f",
                  (unsigned long)millis(),
                  (unsigned)activeAddr,
                  (unsigned)repRaw,
                  (double)repDeg,
                  (unsigned)stopRaw,
                  (double)stopDeg,
                  (unsigned)stopSwapRaw,
                  (double)stopSwapDeg);
    printRead_("rep2", angleRepeated, 2);
    printRead_("stop2", angleStop, 2);
    printRead_("stop6", blockStop, 6);
    printRead_("direct2", direct2, 2);
    Serial.println();
    delay((uint32_t)BODAQS_AS5048_PROBE_PERIOD_MS);
  }

  const bool stopValidationReads = ((int)BODAQS_AS5048_PROBE_STOP_READS != 0);
  Serial.printf("[AS5048-PROBE] validation mode: addr=0x%02X %s reads, period=%lu ms\n",
                (unsigned)activeAddr,
                stopValidationReads ? "STOP-then-read" : "repeated-start",
                (unsigned long)BODAQS_AS5048_PROBE_PERIOD_MS);
  Serial.printf("[AS5048-PROBE] diagnostics: OCF=diag&0x%02X COF=diag&0x%02X MAG_HIGH=diag&0x%02X MAG_LOW=diag&0x%02X\n",
                (unsigned)kDiagOcf,
                (unsigned)kDiagCof,
                (unsigned)kDiagCompLow,
                (unsigned)kDiagCompHigh);
  printValidationHeader_();

  bool havePreviousRaw = false;
  uint16_t previousRaw = 0;
  while (true) {
    probeWire.setClock((uint32_t)BODAQS_AS5048_PROBE_HZ);
    const ValidationSample sample = readValidationSample_(probeWire,
                                                          activeAddr,
                                                          stopValidationReads,
                                                          havePreviousRaw,
                                                          previousRaw);
    printValidationRow_(sample);
    delay((uint32_t)BODAQS_AS5048_PROBE_PERIOD_MS);
  }
}

#endif
