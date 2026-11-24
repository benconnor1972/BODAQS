#include "RecordingFeatures.h"
#ifndef STORAGE_MANAGER_H
#define STORAGE_MANAGER_H

#include <Arduino.h>
#include "SD_MMC.h"
#include "BoardProfile.h"   // make sure this is available
#include "TimingStats.h"
#include "RawAdcRecording.h"

namespace board { struct BoardProfile; }  // forward decl (your renamed namespace)

void StorageManager_begin(const board::BoardProfile& bp);
void StorageManager_setSampleRate(unsigned int hz);
void StorageManager_setBufferSize(size_t bytes);
// Rounded-up compatibility view for legacy callers; new scheduling code uses us.
unsigned long StorageManager_getSampleIntervalMs();
uint32_t StorageManager_getSampleIntervalUs();
unsigned int StorageManager_getSampleRateHz();
// ESP32: queues open/health I/O; true means accepted, not acquisition ready.
bool StorageManager_startLog();
// Reserve the persistent idle storage worker without requesting I/O or opening
// a file. startLog() also ensures it for existing callers.
bool StorageManager_prepareTask();
// ESP32: requests owner finalization and returns without waiting for SD.
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
#if BODAQS_RAW_COUNT_RECORDING
bool StorageManager_enqueueRawAdc(const RawAdcRecord& record,bool mark,uint64_t markTime,uint64_t capturedUs);
RawAdcRecordingStats StorageManager_rawAdcStats(); // Retired owners only.
#endif
// Owner-only drain on ESP32; control callers return without performing I/O.
// The recording controller feeds final sensor rows before requesting Stop.
void StorageManager_drainQueuedSamples();

bool StorageManager_loadTextFile(const char* path, String& out);
bool StorageManager_saveTextFile(const char* path, const String& data);
// Startup-only: bounded 32-slot rotation, using the existing atomic text save.
// Refuses to write while acquisition/logging is active or SD is unavailable.
bool StorageManager_saveStartupReport(const char* body, char* savedPath, size_t pathCapacity);
StorageTimingStats StorageManager_timingStats();

bool StorageManager_cardDetected();
bool StorageManager_cardDetectAvailable();
bool StorageManager_cardDetectedCached();
bool StorageManager_isMounted();
bool StorageManager_readyForLogging();
bool StorageManager_remountIfPresent();
const char* StorageManager_lastStatus();


// Debug: SD write tracking flag (set when any SD write occurred since last sample)
// and a toggle to enable/disable tracking.
extern volatile bool g_sdWriteSinceLastSample;
extern bool g_sdTrackEnabled;


// Actual requested allocation sizes for the current/last BDQ-v2 start. Heap
// allocator overhead, filesystem internals and task watermarks are not measured.
// Fields are independently published observations, not an atomic heap snapshot.
struct StorageRecordingAllocation {
  size_t primaryQueueBytes = 0;
  size_t workspaceBytes = 0;
  size_t outputBufferBytes = 0;
  size_t catalogPeakBytes = 0;
  size_t primaryColumnsPeakBytes = 0;
  size_t metadataPayloadBytes = 0;
  size_t staticStateBytes = 0;
  size_t storageTaskStackBytes = 0;
};
StorageRecordingAllocation StorageManager_recordingAllocation();

// Nonblocking observations; pending includes startup, recording and finalization.
bool StorageManager_recordingIoPending();
#if defined(BODAQS_ADAPTIVE_DRAIN_OWNER) && BODAQS_ADAPTIVE_DRAIN_OWNER
// Hints only: static atomic indices and separately published capacity tolerate STOP/reset.
size_t StorageManager_primaryPendingForBalance();
size_t StorageManager_primaryCapacityForBalance();
#endif
bool StorageManager_recordingReady();
bool StorageManager_storageFault();
bool StorageManager_canAcceptSample();
bool StorageManager_storageUnresponsive();

#endif
