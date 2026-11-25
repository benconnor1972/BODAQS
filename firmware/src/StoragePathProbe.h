#pragma once
#include <stddef.h>
#include <stdint.h>
#ifndef BODAQS_STORAGE_PATH_PROBE
#define BODAQS_STORAGE_PATH_PROBE 0
#endif

namespace StoragePathProbe {
#if BODAQS_STORAGE_PATH_PROBE
void bootGate();
// Only the persistent StorageTask calls begin/finish and mutates counters.
// The scope includes file open, FAT/directory work, file data and close.
void begin(uint64_t context);
void finish(bool clean);
uint32_t payloadCrc(const uint8_t* data, size_t length);
#else
inline void bootGate() {}
inline void begin(uint64_t) {}
inline void finish(bool) {}
#endif
} // namespace StoragePathProbe
