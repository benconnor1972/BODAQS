#ifndef STORAGE_MANAGER_H
#define STORAGE_MANAGER_H

#include <Arduino.h>
#include <SdFat.h>

void StorageManager_begin(uint8_t csPin);
void StorageManager_setSampleRate(unsigned int hz);
void StorageManager_setBufferSize(size_t bytes);
unsigned long StorageManager_getSampleIntervalMs();   // <-- NEW
void StorageManager_logRecord(float pot1, float pot2, float strain, float accelX, float accelY, float accelZ, float accelTemp, bool mark);
void StorageManager_logRecordWithTs(uint64_t epochMs, float pot1, float pot2, float strain, float accelX, float accelY, float accelZ, float accelTemp, bool mark);
void StorageManager_startLog();
void StorageManager_stopLog();
void StorageManager_loop();
void StorageManager_setCustomHeader(const char* csv);
void StorageManager_logCsvDynamic(uint64_t ts_ms, const float* values, uint16_t n, bool mark);


// Give other modules access to the already-initialized SdFat instance
SdFat* StorageManager_getSd();
extern SdFat* gSd;
#endif
