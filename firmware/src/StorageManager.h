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
unsigned long StorageManager_getSampleIntervalMs();   // <-- NEW
bool StorageManager_startLog();
void StorageManager_stopLog();
void StorageManager_loop();
void StorageManager_setCustomHeader(const char* csv);
void StorageManager_logCsvDynamic(uint32_t sample_id, uint64_t ts_ms, const float* values, uint16_t n, bool mark);
bool StorageManager_enqueueSample(uint32_t sample_id, uint64_t ts_ms, const float* values, uint16_t n, bool mark);

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
