#pragma once

#include <Arduino.h>

struct ZipArchiveEntry {
  const char* sourcePath = nullptr;
  const char* archiveName = nullptr;
};

bool ZipArchiveWriter_createStoreOnly(const char* destinationPath,
                                      const ZipArchiveEntry* entries,
                                      uint8_t entryCount,
                                      String* error = nullptr);

