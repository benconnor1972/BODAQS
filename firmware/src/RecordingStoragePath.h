#pragma once
#include <stddef.h>
#include <stdint.h>

#ifndef BODAQS_PRODUCTION_RECORDING
#define BODAQS_PRODUCTION_RECORDING 0
#endif

namespace RecordingStoragePath {
#if BODAQS_PRODUCTION_RECORDING
// Called only by the persistent storage owner, before file open and after close.
// A failed reservation leaves ownership free and permits a later explicit retry.
bool begin();
void finish();
uint32_t payloadCrc(const uint8_t* data, size_t length);
#else
inline bool begin() { return true; }
inline void finish() {}
#endif
}
