#include "ZipArchiveWriter.h"

#include <time.h>
#include "SD_MMC.h"

namespace {

constexpr uint8_t kMaxZipEntries = 8;

struct ZipEntryMeta {
  String name;
  uint32_t crc = 0;
  uint32_t size = 0;
  uint32_t localOffset = 0;
};

static void setError_(String* error, const __FlashStringHelper* msg) {
  if (error) *error = String(msg);
}

static void setError_(String* error, const String& msg) {
  if (error) *error = msg;
}

static String normalizeAbsPath_(const char* path) {
  if (!path || !*path) return String();
  String out(path);
  if (!out.startsWith("/")) out = "/" + out;
  return out;
}

static uint32_t crc32Update_(uint32_t crc, const uint8_t* data, size_t len) {
  crc = ~crc;
  for (size_t i = 0; i < len; ++i) {
    crc ^= data[i];
    for (int k = 0; k < 8; ++k) {
      crc = (crc >> 1) ^ (0xEDB88320u & (-(int32_t)(crc & 1u)));
    }
  }
  return ~crc;
}

static bool writeBytes_(File& out, const void* data, size_t len, uint32_t& bytesWritten) {
  if (len == 0) return true;
  const size_t written = out.write(static_cast<const uint8_t*>(data), len);
  if (written != len) return false;
  bytesWritten += static_cast<uint32_t>(written);
  return true;
}

static bool writeU16_(File& out, uint16_t v, uint32_t& bytesWritten) {
  uint8_t b[2] = {
    static_cast<uint8_t>(v & 0xFF),
    static_cast<uint8_t>((v >> 8) & 0xFF),
  };
  return writeBytes_(out, b, sizeof(b), bytesWritten);
}

static bool writeU32_(File& out, uint32_t v, uint32_t& bytesWritten) {
  uint8_t b[4] = {
    static_cast<uint8_t>(v & 0xFF),
    static_cast<uint8_t>((v >> 8) & 0xFF),
    static_cast<uint8_t>((v >> 16) & 0xFF),
    static_cast<uint8_t>((v >> 24) & 0xFF),
  };
  return writeBytes_(out, b, sizeof(b), bytesWritten);
}

static void zipDosTimeDate_(uint16_t& dosTime, uint16_t& dosDate) {
  time_t now = time(nullptr);
  if (now <= 100000) {
    dosTime = 0;
    dosDate = 0;
    return;
  }

  struct tm t;
  localtime_r(&now, &t);

  dosTime = static_cast<uint16_t>(((t.tm_sec / 2) & 0x1F) |
                                  ((t.tm_min & 0x3F) << 5) |
                                  ((t.tm_hour & 0x1F) << 11));

  int year = t.tm_year + 1900;
  if (year < 1980) year = 1980;
  dosDate = static_cast<uint16_t>((t.tm_mday & 0x1F) |
                                  (((t.tm_mon + 1) & 0x0F) << 5) |
                                  (((year - 1980) & 0x7F) << 9));
}

static bool validateEntry_(const ZipArchiveEntry& entry, String* error) {
  if (!entry.sourcePath || !*entry.sourcePath) {
    setError_(error, F("entry missing source path"));
    return false;
  }
  if (!entry.archiveName || !*entry.archiveName) {
    setError_(error, F("entry missing archive name"));
    return false;
  }

  const String name(entry.archiveName);
  if (name.indexOf('/') >= 0 || name.indexOf('\\') >= 0) {
    setError_(error, String(F("archive name must be a file name: ")) + name);
    return false;
  }
  if (name.length() > 65535) {
    setError_(error, String(F("archive name too long: ")) + name);
    return false;
  }

  return true;
}

} // namespace

bool ZipArchiveWriter_createStoreOnly(const char* destinationPath,
                                      const ZipArchiveEntry* entries,
                                      uint8_t entryCount,
                                      String* error) {
  if (error) *error = "";

  const String dest = normalizeAbsPath_(destinationPath);
  if (!dest.length()) {
    setError_(error, F("missing destination path"));
    return false;
  }
  if (!entries || entryCount == 0) {
    setError_(error, F("no entries"));
    return false;
  }
  if (entryCount > kMaxZipEntries) {
    setError_(error, F("too many entries"));
    return false;
  }
  if (SD_MMC.exists(dest.c_str())) {
    setError_(error, String(F("destination already exists: ")) + dest);
    return false;
  }

  for (uint8_t i = 0; i < entryCount; ++i) {
    if (!validateEntry_(entries[i], error)) return false;
    const String source = normalizeAbsPath_(entries[i].sourcePath);
    File f = SD_MMC.open(source.c_str(), FILE_READ);
    if (!f) {
      setError_(error, String(F("source open failed: ")) + source);
      return false;
    }
    if (f.isDirectory()) {
      f.close();
      setError_(error, String(F("source is directory: ")) + source);
      return false;
    }
    if (static_cast<uint64_t>(f.size()) > 0xFFFFFFFFULL) {
      f.close();
      setError_(error, String(F("source too large for ZIP32: ")) + source);
      return false;
    }
    f.close();
  }

  File out = SD_MMC.open(dest.c_str(), FILE_WRITE);
  if (!out) {
    setError_(error, String(F("destination open failed: ")) + dest);
    return false;
  }
  out.seek(0);

  uint16_t dosTime = 0;
  uint16_t dosDate = 0;
  zipDosTimeDate_(dosTime, dosDate);

  ZipEntryMeta meta[kMaxZipEntries];
  uint32_t bytesWritten = 0;
  static uint8_t buf[2048];

  for (uint8_t i = 0; i < entryCount; ++i) {
    const String source = normalizeAbsPath_(entries[i].sourcePath);
    const String name(entries[i].archiveName);

    meta[i].name = name;
    meta[i].localOffset = bytesWritten;

    bool ok =
      writeU32_(out, 0x04034b50u, bytesWritten) &&
      writeU16_(out, 20, bytesWritten) &&
      writeU16_(out, 0x0008, bytesWritten) &&
      writeU16_(out, 0, bytesWritten) &&
      writeU16_(out, dosTime, bytesWritten) &&
      writeU16_(out, dosDate, bytesWritten) &&
      writeU32_(out, 0, bytesWritten) &&
      writeU32_(out, 0, bytesWritten) &&
      writeU32_(out, 0, bytesWritten) &&
      writeU16_(out, static_cast<uint16_t>(name.length()), bytesWritten) &&
      writeU16_(out, 0, bytesWritten) &&
      writeBytes_(out, name.c_str(), name.length(), bytesWritten);

    if (!ok) {
      out.close();
      setError_(error, String(F("write failed while writing header: ")) + name);
      return false;
    }

    uint32_t crc = 0;
    uint32_t size = 0;
    File in = SD_MMC.open(source.c_str(), FILE_READ);
    if (!in) {
      out.close();
      setError_(error, String(F("source reopen failed: ")) + source);
      return false;
    }

    int n = 0;
    while ((n = in.read(buf, sizeof(buf))) > 0) {
      crc = crc32Update_(crc, buf, static_cast<size_t>(n));
      size += static_cast<uint32_t>(n);
      if (!writeBytes_(out, buf, static_cast<size_t>(n), bytesWritten)) {
        in.close();
        out.close();
        setError_(error, String(F("write failed while writing data: ")) + name);
        return false;
      }
      delay(0);
    }
    in.close();

    meta[i].crc = crc;
    meta[i].size = size;

    ok =
      writeU32_(out, 0x08074b50u, bytesWritten) &&
      writeU32_(out, crc, bytesWritten) &&
      writeU32_(out, size, bytesWritten) &&
      writeU32_(out, size, bytesWritten);

    if (!ok) {
      out.close();
      setError_(error, String(F("write failed while writing descriptor: ")) + name);
      return false;
    }
  }

  const uint32_t centralStart = bytesWritten;

  for (uint8_t i = 0; i < entryCount; ++i) {
    const String& name = meta[i].name;
    const bool ok =
      writeU32_(out, 0x02014b50u, bytesWritten) &&
      writeU16_(out, 20, bytesWritten) &&
      writeU16_(out, 20, bytesWritten) &&
      writeU16_(out, 0x0008, bytesWritten) &&
      writeU16_(out, 0, bytesWritten) &&
      writeU16_(out, dosTime, bytesWritten) &&
      writeU16_(out, dosDate, bytesWritten) &&
      writeU32_(out, meta[i].crc, bytesWritten) &&
      writeU32_(out, meta[i].size, bytesWritten) &&
      writeU32_(out, meta[i].size, bytesWritten) &&
      writeU16_(out, static_cast<uint16_t>(name.length()), bytesWritten) &&
      writeU16_(out, 0, bytesWritten) &&
      writeU16_(out, 0, bytesWritten) &&
      writeU16_(out, 0, bytesWritten) &&
      writeU16_(out, 0, bytesWritten) &&
      writeU32_(out, 0, bytesWritten) &&
      writeU32_(out, meta[i].localOffset, bytesWritten) &&
      writeBytes_(out, name.c_str(), name.length(), bytesWritten);

    if (!ok) {
      out.close();
      setError_(error, String(F("write failed while writing central directory: ")) + name);
      return false;
    }
  }

  const uint32_t centralSize = bytesWritten - centralStart;
  const bool ok =
    writeU32_(out, 0x06054b50u, bytesWritten) &&
    writeU16_(out, 0, bytesWritten) &&
    writeU16_(out, 0, bytesWritten) &&
    writeU16_(out, entryCount, bytesWritten) &&
    writeU16_(out, entryCount, bytesWritten) &&
    writeU32_(out, centralSize, bytesWritten) &&
    writeU32_(out, centralStart, bytesWritten) &&
    writeU16_(out, 0, bytesWritten);

  out.flush();
  out.close();

  if (!ok) {
    setError_(error, F("write failed while finishing archive"));
    return false;
  }

  return true;
}

