#ifndef STORAGE_MANAGER_H
#define STORAGE_MANAGER_H

#include <Arduino.h>
#include "SD_MMC.h"
#include "BoardProfile.h"   // make sure this is available
#include "TimingStats.h"

namespace board { struct BoardProfile; }  // forward decl (your renamed namespace)

void StorageManager_begin(const board::BoardProfile& bp);
void StorageManager_setSampleRate(unsigned int hz);
void StorageManager_setBufferSize(size_t bytes);
// Rounded-up compatibility view for legacy callers; new scheduling code uses us.
unsigned long StorageManager_getSampleIntervalMs();
uint32_t StorageManager_getSampleIntervalUs();
unsigned int StorageManager_getSampleRateHz();
bool StorageManager_startLog();
void StorageManager_stopLog();
void StorageManager_loop();
void StorageManager_setCustomHeader(const char* csv);
void StorageManager_logCsvDynamic(uint32_t sample_id, uint64_t ts_ms, const float* values, uint16_t n, bool mark);
bool StorageManager_enqueueSample(
    uint32_t sample_id,
    uint64_t ts_ms,
    const float* values,
    uint16_t n,
    bool mark,
    uint64_t hostMonotonicUs = 0,
    uint64_t markHostMonotonicUs = 0);
bool StorageManager_usesIndependentStreams();
// Requires the logger sampler to be quiesced. Used during orderly shutdown so
// final sensor FIFO rows cannot be lost behind a full storage queue.
void StorageManager_drainQueuedSamples();

bool StorageManager_loadTextFile(const char* path, String& out);
bool StorageManager_saveTextFile(const char* path, const String& data);
StorageTimingStats StorageManager_timingStats();

bool StorageManager_cardDetected();
bool StorageManager_isMounted();
bool StorageManager_readyForLogging();
bool StorageManager_remountIfPresent();
const char* StorageManager_lastStatus();


// Debug: SD write tracking flag (set when any SD write occurred since last sample)
// and a toggle to enable/disable tracking.
extern volatile bool g_sdWriteSinceLastSample;
extern bool g_sdTrackEnabled;


#endif
