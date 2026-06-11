#include "HttpFileSender.h"

#include "SD_MMC.h"
#include <errno.h>
#include <lwip/sockets.h>

namespace {

static constexpr uint32_t kWriteStallTimeoutMs = 1500;
static constexpr uint32_t kWriteSelectTimeoutUs = 25000;

static String contentRange_(uint32_t start, uint32_t end, uint32_t total) {
  return String(F("bytes ")) + String(start) + F("-") + String(end) + F("/") + String(total);
}

static bool parseUint_(const String& s, uint32_t& out) {
  if (!s.length()) return false;
  uint64_t value = 0;
  for (uint16_t i = 0; i < s.length(); ++i) {
    const char c = s[i];
    if (c < '0' || c > '9') return false;
    value = value * 10ULL + uint64_t(c - '0');
    if (value > 0xFFFFFFFFULL) return false;
  }
  out = (uint32_t)value;
  return true;
}

static bool parseRange_(const String& header,
                        uint32_t total,
                        bool& hasRange,
                        uint32_t& start,
                        uint32_t& end) {
  hasRange = false;
  start = 0;
  end = total ? total - 1 : 0;

  String h = header;
  h.trim();
  if (!h.length()) return true;
  if (!h.startsWith("bytes=")) return false;
  if (h.indexOf(',') >= 0) return false; // multipart ranges are deliberately unsupported

  String spec = h.substring(6);
  spec.trim();
  const int dash = spec.indexOf('-');
  if (dash < 0) return false;

  const String first = spec.substring(0, dash);
  const String last = spec.substring(dash + 1);

  if (!first.length()) {
    uint32_t suffix = 0;
    if (!parseUint_(last, suffix) || suffix == 0) return false;
    hasRange = true;
    if (suffix >= total) {
      start = 0;
    } else {
      start = total - suffix;
    }
    end = total ? total - 1 : 0;
    return total > 0;
  }

  uint32_t parsedStart = 0;
  if (!parseUint_(first, parsedStart)) return false;

  uint32_t parsedEnd = total ? total - 1 : 0;
  if (last.length() && !parseUint_(last, parsedEnd)) return false;

  if (total == 0 || parsedStart >= total || parsedEnd < parsedStart) return false;
  if (parsedEnd >= total) parsedEnd = total - 1;

  hasRange = true;
  start = parsedStart;
  end = parsedEnd;
  return true;
}

static void sendRangeNotSatisfiable_(WebServer& srv, uint32_t total) {
  srv.sendHeader(F("Accept-Ranges"), F("bytes"));
  srv.sendHeader(F("Content-Range"), String(F("bytes */")) + String(total));
  srv.send(416, F("text/plain"), F("Requested range not satisfiable"));
}

static bool writeClientChunk_(WiFiClient& client, const uint8_t* data, size_t len) {
  int fd = client.fd();
  if (fd < 0 || !client.connected()) return false;

  size_t sent = 0;
  uint32_t lastProgressMs = millis();

  while (sent < len) {
    if (!client.connected()) return false;

    fd_set writeSet;
    FD_ZERO(&writeSet);
    FD_SET(fd, &writeSet);

    struct timeval timeout;
    timeout.tv_sec = 0;
    timeout.tv_usec = kWriteSelectTimeoutUs;

    const int ready = select(fd + 1, nullptr, &writeSet, nullptr, &timeout);
    if (ready < 0) {
      client.stop();
      return false;
    }

    if (ready == 0 || !FD_ISSET(fd, &writeSet)) {
      if ((uint32_t)(millis() - lastProgressMs) >= kWriteStallTimeoutMs) {
        client.stop();
        return false;
      }
      delay(0);
      continue;
    }

    const int n = send(fd, data + sent, len - sent, MSG_DONTWAIT);
    if (n > 0) {
      sent += (size_t)n;
      lastProgressMs = millis();
      continue;
    }

    if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)) {
      if ((uint32_t)(millis() - lastProgressMs) >= kWriteStallTimeoutMs) {
        client.stop();
        return false;
      }
      delay(0);
      continue;
    }

    client.stop();
    return false;
  }

  return true;
}

} // namespace

namespace HttpFileSender {

bool writeResponseChunk(WebServer& srv, const void* data, size_t len) {
  if (len == 0) return true;
  WiFiClient client = srv.client();
  return writeClientChunk_(client, static_cast<const uint8_t*>(data), len);
}

bool sendText(WebServer& srv,
              int statusCode,
              const String& contentType,
              const String& body,
              const String& cacheControl) {
  if (cacheControl.length()) {
    srv.sendHeader(F("Cache-Control"), cacheControl);
  }
  srv.setContentLength(body.length());
  srv.send(statusCode, contentType, "");

  static constexpr size_t kChunkSize = 2048;
  size_t offset = 0;
  const size_t total = body.length();
  const char* data = body.c_str();
  while (offset < total) {
    const size_t n = (total - offset < kChunkSize) ? (total - offset) : kChunkSize;
    if (!writeResponseChunk(srv, data + offset, n)) return false;
    offset += n;
    delay(0);
  }
  return true;
}

bool sendSdFile(WebServer& srv,
                const String& path,
                const String& contentType,
                const String& downloadName,
                const String& cacheControl) {
  File f = SD_MMC.open(path.c_str(), FILE_READ);
  if (!f || f.isDirectory()) {
    if (f) f.close();
    return false;
  }

  const uint32_t total = (uint32_t)f.size();
  bool partial = false;
  uint32_t start = 0;
  uint32_t end = total ? total - 1 : 0;

  if (srv.hasHeader(F("Range"))) {
    if (!parseRange_(srv.header(F("Range")), total, partial, start, end)) {
      f.close();
      sendRangeNotSatisfiable_(srv, total);
      return true;
    }
  }

  const uint32_t bytesToSend = partial ? (end - start + 1) : total;
  if (partial && !f.seek(start)) {
    f.close();
    srv.send(500, F("text/plain"), F("Seek failed"));
    return true;
  }

  if (cacheControl.length()) {
    srv.sendHeader(F("Cache-Control"), cacheControl);
  }
  srv.sendHeader(F("Accept-Ranges"), F("bytes"));
  if (downloadName.length()) {
    srv.sendHeader(F("Content-Disposition"), String(F("attachment; filename=\"")) + downloadName + F("\""));
  }
  if (partial) {
    srv.sendHeader(F("Content-Range"), contentRange_(start, end, total));
  }
  srv.setContentLength(bytesToSend);
  srv.send(partial ? 206 : 200, contentType, "");

  WiFiClient client = srv.client();
  static uint8_t buf[2048];
  uint32_t remaining = bytesToSend;
  while (remaining > 0) {
    const size_t want = (remaining < sizeof(buf)) ? (size_t)remaining : sizeof(buf);
    const int n = f.read(buf, want);
    if (n <= 0) break;
    if (!writeClientChunk_(client, buf, (size_t)n)) break;
    remaining -= (uint32_t)n;
    delay(0);
  }

  f.close();
  return true;
}

}
