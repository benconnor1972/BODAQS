#include "GpsUartProbe.h"

#if defined(BODAQS_GPS_UART_PROBE)

#include <Arduino.h>
#include <HardwareSerial.h>
#include <string.h>

#ifndef BODAQS_GPS_PROBE_UART_PORT
#define BODAQS_GPS_PROBE_UART_PORT 0
#endif

#ifndef BODAQS_GPS_PROBE_SAMPLE_MS
#define BODAQS_GPS_PROBE_SAMPLE_MS 2500UL
#endif

#ifndef BODAQS_GPS_PROBE_RESCAN_MS
#define BODAQS_GPS_PROBE_RESCAN_MS 5000UL
#endif

namespace {

struct BaudStats {
  uint32_t baud = 0;
  uint32_t bytes = 0;
  uint32_t printable = 0;
  uint32_t dollar = 0;
  uint32_t nmeaLines = 0;
  uint32_t ubxSync = 0;
  uint32_t score = 0;
  char text[121] = {0};
  char hex[97] = {0};
};

struct ActiveStats {
  uint32_t baud = 0;
  uint32_t bytes = 0;
  uint32_t printable = 0;
  uint32_t dollar = 0;
  uint32_t nmeaLines = 0;
  uint32_t ubxPackets = 0;
  uint32_t monVerPackets = 0;
  char text[121] = {0};
  char hex[97] = {0};
};

HardwareSerial* serialForPort_(uint8_t port) {
  switch (port) {
    case 0: return &Serial1;
    case 1: return &Serial2;
    default: return nullptr;
  }
}

void appendChar_(char* out, size_t cap, char c) {
  if (!out || cap == 0) return;
  const size_t len = strnlen(out, cap);
  if (len >= cap - 1) return;
  out[len] = c;
  out[len + 1] = '\0';
}

void appendHex_(char* out, size_t cap, uint8_t b) {
  if (!out || cap == 0) return;
  const size_t len = strnlen(out, cap);
  if (len >= cap - 4) return;
  snprintf(out + len, cap - len, "%s%02X", len ? " " : "", (unsigned)b);
}

bool looksPlausible_(const BaudStats& s) {
  if (s.nmeaLines > 0 || s.ubxSync > 0) return true;
  if (s.bytes < 20) return false;
  const uint32_t printablePct = (s.printable * 100UL) / s.bytes;
  return printablePct >= 70 && s.dollar > 0;
}

uint32_t score_(const BaudStats& s) {
  if (s.bytes == 0) return 0;
  const uint32_t printablePct = (s.printable * 100UL) / s.bytes;
  uint32_t score = printablePct;
  score += s.dollar * 300UL;
  score += s.nmeaLines * 1000UL;
  score += s.ubxSync * 1000UL;
  if (s.bytes > 20 && printablePct >= 70) score += 200UL;
  return score;
}

BaudStats sniffBaud_(HardwareSerial& port, int8_t rxPin, uint32_t baud, uint32_t sampleMs) {
  BaudStats s;
  s.baud = baud;

  port.end();
  delay(50);
  port.begin(baud, SERIAL_8N1, rxPin, -1);
  delay(50);
  while (port.available()) (void)port.read();

  bool havePrev = false;
  uint8_t prev = 0;
  bool lineActive = false;
  char line[96] = {0};
  uint8_t lineLen = 0;

  const uint32_t start = millis();
  while ((uint32_t)(millis() - start) < sampleMs) {
    while (port.available()) {
      const int v = port.read();
      if (v < 0) continue;
      const uint8_t b = (uint8_t)v;
      ++s.bytes;

      if (s.bytes <= 32) appendHex_(s.hex, sizeof(s.hex), b);

      if (b >= 32 && b <= 126) {
        ++s.printable;
        appendChar_(s.text, sizeof(s.text), (char)b);
      } else if (b == '\r' || b == '\n') {
        appendChar_(s.text, sizeof(s.text), ' ');
      }

      if (b == '$') {
        ++s.dollar;
        lineActive = true;
        lineLen = 0;
        line[lineLen++] = (char)b;
        line[lineLen] = '\0';
      } else if (lineActive && (b == '\r' || b == '\n')) {
        if (lineLen >= 6 && line[0] == '$' && line[1] == 'G') ++s.nmeaLines;
        lineActive = false;
        lineLen = 0;
        line[0] = '\0';
      } else if (lineActive) {
        if (lineLen < sizeof(line) - 1) {
          line[lineLen++] = (char)b;
          line[lineLen] = '\0';
        } else {
          lineActive = false;
        }
      }

      if (havePrev && prev == 0xB5 && b == 0x62) ++s.ubxSync;
      prev = b;
      havePrev = true;
    }
    delay(1);
  }

  s.score = score_(s);
  port.end();
  delay(20);
  return s;
}

void printStats_(const BaudStats& s) {
  const uint32_t printablePct = s.bytes ? ((s.printable * 100UL) / s.bytes) : 0;
  Serial.printf("[GPS-PROBE] PASSIVE baud=%lu bytes=%lu printable=%lu%% dollar=%lu nmea_lines=%lu ubx_sync=%lu score=%lu plausible=%u hex=\"%s\" text=\"%s\"\n",
                (unsigned long)s.baud,
                (unsigned long)s.bytes,
                (unsigned long)printablePct,
                (unsigned long)s.dollar,
                (unsigned long)s.nmeaLines,
                (unsigned long)s.ubxSync,
                (unsigned long)s.score,
                looksPlausible_(s) ? 1u : 0u,
                s.hex,
                s.text);
}

ActiveStats pollMonVer_(HardwareSerial& port, int8_t rxPin, int8_t txPin, uint32_t baud, uint32_t waitMs) {
  ActiveStats s;
  s.baud = baud;

  static const uint8_t kUbxMonVerPoll[] = {
    0xB5, 0x62, 0x0A, 0x04, 0x00, 0x00, 0x0E, 0x34
  };

  port.end();
  delay(50);
  port.begin(baud, SERIAL_8N1, rxPin, txPin);
  delay(100);
  while (port.available()) (void)port.read();

  port.write(kUbxMonVerPoll, sizeof(kUbxMonVerPoll));
  port.flush();

  enum class UbxState : uint8_t {
    Sync1,
    Sync2,
    Class,
    Id,
    Len1,
    Len2,
    Payload,
    CkA,
    CkB,
  };

  UbxState ubxState = UbxState::Sync1;
  uint8_t ubxClass = 0;
  uint8_t ubxId = 0;
  uint16_t ubxLen = 0;
  uint16_t ubxSeen = 0;
  bool havePrev = false;
  uint8_t prev = 0;
  bool lineActive = false;
  char line[96] = {0};
  uint8_t lineLen = 0;

  const uint32_t start = millis();
  while ((uint32_t)(millis() - start) < waitMs) {
    while (port.available()) {
      const int v = port.read();
      if (v < 0) continue;
      const uint8_t b = (uint8_t)v;
      ++s.bytes;

      if (s.bytes <= 32) appendHex_(s.hex, sizeof(s.hex), b);
      if (b >= 32 && b <= 126) {
        ++s.printable;
        appendChar_(s.text, sizeof(s.text), (char)b);
      } else if (b == '\r' || b == '\n') {
        appendChar_(s.text, sizeof(s.text), ' ');
      }

      if (b == '$') {
        ++s.dollar;
        lineActive = true;
        lineLen = 0;
        line[lineLen++] = (char)b;
        line[lineLen] = '\0';
      } else if (lineActive && (b == '\r' || b == '\n')) {
        if (lineLen >= 6 && line[0] == '$' && line[1] == 'G') ++s.nmeaLines;
        lineActive = false;
        lineLen = 0;
        line[0] = '\0';
      } else if (lineActive) {
        if (lineLen < sizeof(line) - 1) {
          line[lineLen++] = (char)b;
          line[lineLen] = '\0';
        } else {
          lineActive = false;
        }
      }

      switch (ubxState) {
        case UbxState::Sync1:
          ubxState = (b == 0xB5) ? UbxState::Sync2 : UbxState::Sync1;
          break;
        case UbxState::Sync2:
          ubxState = (b == 0x62) ? UbxState::Class : ((b == 0xB5) ? UbxState::Sync2 : UbxState::Sync1);
          break;
        case UbxState::Class:
          ubxClass = b;
          ubxState = UbxState::Id;
          break;
        case UbxState::Id:
          ubxId = b;
          ubxState = UbxState::Len1;
          break;
        case UbxState::Len1:
          ubxLen = b;
          ubxState = UbxState::Len2;
          break;
        case UbxState::Len2:
          ubxLen |= (uint16_t(b) << 8);
          ubxSeen = 0;
          ubxState = (ubxLen == 0) ? UbxState::CkA : UbxState::Payload;
          break;
        case UbxState::Payload:
          ++ubxSeen;
          if (ubxSeen >= ubxLen) ubxState = UbxState::CkA;
          break;
        case UbxState::CkA:
          ubxState = UbxState::CkB;
          break;
        case UbxState::CkB:
          ++s.ubxPackets;
          if (ubxClass == 0x0A && ubxId == 0x04) ++s.monVerPackets;
          ubxState = UbxState::Sync1;
          break;
      }

      prev = b;
      havePrev = true;
      (void)prev;
      (void)havePrev;
    }
    delay(1);
  }

  port.end();
  delay(20);
  return s;
}

void printActiveStats_(const ActiveStats& s) {
  const uint32_t printablePct = s.bytes ? ((s.printable * 100UL) / s.bytes) : 0;
  Serial.printf("[GPS-PROBE] ACTIVE_MONVER baud=%lu bytes=%lu printable=%lu%% dollar=%lu nmea_lines=%lu ubx_packets=%lu mon_ver=%lu hex=\"%s\" text=\"%s\"\n",
                (unsigned long)s.baud,
                (unsigned long)s.bytes,
                (unsigned long)printablePct,
                (unsigned long)s.dollar,
                (unsigned long)s.nmeaLines,
                (unsigned long)s.ubxPackets,
                (unsigned long)s.monVerPackets,
                s.hex,
                s.text);
}

void streamBaud_(HardwareSerial& port, int8_t rxPin, uint32_t baud) {
  Serial.printf("[GPS-PROBE] streaming passive RX at %lu baud. Reset board to rescan.\n",
                (unsigned long)baud);
  Serial.println("[GPS-PROBE] printable data follows; non-printable bytes shown as <XX>.");

  port.end();
  delay(50);
  port.begin(baud, SERIAL_8N1, rxPin, -1);

  uint32_t lastStatsMs = millis();
  uint32_t bytes = 0;
  while (true) {
    while (port.available()) {
      const int v = port.read();
      if (v < 0) continue;
      const uint8_t b = (uint8_t)v;
      ++bytes;
      if (b == '\r' || b == '\n') {
        Serial.write(b);
      } else if (b >= 32 && b <= 126) {
        Serial.write(b);
      } else {
        Serial.printf("<%02X>", (unsigned)b);
      }
    }

    const uint32_t now = millis();
    if ((uint32_t)(now - lastStatsMs) >= 5000UL) {
      Serial.printf("\n[GPS-PROBE] stream baud=%lu bytes_last_5s=%lu\n",
                    (unsigned long)baud,
                    (unsigned long)bytes);
      bytes = 0;
      lastStatsMs = now;
    }
    delay(1);
  }
}

} // namespace

void RunGpsUartProbe(const board::BoardProfile& bp) {
  const uint8_t uartIndex = (uint8_t)BODAQS_GPS_PROBE_UART_PORT;

  Serial.println();
  Serial.println("[GPS-PROBE] DAN-F10N UART passive baud probe");
  Serial.println("[GPS-PROBE] RX-only scan: BODAQS TX is not driven during scan.");

  if (uartIndex >= bp.uart_count || uartIndex >= board::BOARD_MAX_UART_PORTS ||
      !bp.uart[uartIndex].present) {
    Serial.printf("[GPS-PROBE] board profile has no present UART%u\n",
                  (unsigned)uartIndex);
    while (true) delay(1000);
  }

  const auto& uart = bp.uart[uartIndex];
  if (uart.rx < 0) {
    Serial.printf("[GPS-PROBE] invalid UART%u RX pin: %d\n",
                  (unsigned)uartIndex,
                  (int)uart.rx);
    while (true) delay(1000);
  }

  HardwareSerial* port = serialForPort_(uartIndex);
  if (!port) {
    Serial.printf("[GPS-PROBE] no HardwareSerial instance for UART%u\n",
                  (unsigned)uartIndex);
    while (true) delay(1000);
  }

  Serial.printf("[GPS-PROBE] board=%s UART%u esp_tx=%d esp_rx=%d default_baud=%lu\n",
                bp.name ? bp.name : "(null)",
                (unsigned)uartIndex,
                (int)uart.tx,
                (int)uart.rx,
                (unsigned long)uart.baud_default);
  Serial.printf("[GPS-PROBE] expected wiring: GPS TXD -> ESP32 GPIO%d, GPS RXD <- ESP32 GPIO%d\n",
                (int)uart.rx,
                (int)uart.tx);
  Serial.printf("[GPS-PROBE] sample_ms=%lu\n", (unsigned long)BODAQS_GPS_PROBE_SAMPLE_MS);

  static const uint32_t bauds[] = {
    38400UL,
    9600UL,
    115200UL,
    57600UL,
    19200UL,
    230400UL,
    460800UL,
    921600UL,
  };

  while (true) {
    BaudStats best;
    Serial.println("[GPS-PROBE] scan_start");
    for (uint8_t i = 0; i < sizeof(bauds) / sizeof(bauds[0]); ++i) {
      BaudStats s = sniffBaud_(*port, uart.rx, bauds[i], (uint32_t)BODAQS_GPS_PROBE_SAMPLE_MS);
      printStats_(s);
      if (looksPlausible_(s) && s.score > best.score) best = s;
    }
    Serial.println("[GPS-PROBE] scan_end");

    if (best.baud != 0) {
      Serial.printf("[GPS-PROBE] best_baud=%lu score=%lu. If normal firmware still fails at this baud, suspect GPS RXD/ESP TX path or UART bus contention.\n",
                    (unsigned long)best.baud,
                    (unsigned long)best.score);
      if (uart.tx >= 0) {
        Serial.println("[GPS-PROBE] active_test_start: sending UBX-MON-VER poll on ESP TX");
        ActiveStats active = pollMonVer_(*port, uart.rx, uart.tx, best.baud, 1500UL);
        printActiveStats_(active);
        if (active.monVerPackets > 0) {
          Serial.println("[GPS-PROBE] active_test_result=PASS two-way UART works; normal firmware issue is likely driver/config sequencing.");
        } else {
          Serial.println("[GPS-PROBE] active_test_result=FAIL no UBX-MON-VER response; suspect ESP TX -> GPS RX wiring, GPS RXD jumper/contention, or GPS input protocol disabled.");
        }
      } else {
        Serial.println("[GPS-PROBE] active_test_skipped: board UART TX pin is invalid");
      }
      streamBaud_(*port, uart.rx, best.baud);
    }

    Serial.printf("[GPS-PROBE] no plausible UART data detected; rescanning in %lu ms\n",
                  (unsigned long)BODAQS_GPS_PROBE_RESCAN_MS);
    delay((uint32_t)BODAQS_GPS_PROBE_RESCAN_MS);
  }
}

#endif
