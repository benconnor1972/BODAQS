#pragma once
#include <stdint.h>
#include "ImuAdmission.h"
struct LoggerConfig;
struct BdqV2StreamDescriptor;
namespace RemoteImuRecording {
// Allocation, reconciliation and lifecycle startup run while local acquisition
// is stopped. All selected remote resources precede PREPARE.
bool configure(const LoggerConfig&);
const ImuAdmission::Report& admission();
bool setAdmissionProfile(const ImuAdmission::Profile&);
// Called only after the storage owner has allocated all buffers and written
// the frozen candidate catalog. It is the barrier before any PREPARE.
bool resourcesReady(size_t storageReservedBytes=0);
bool configured();
bool prepared();
bool recording();
bool failed();
const char* failureReason();
void start();
void stop();
void service(); // main-loop orchestration, never transport/storage progress
bool stopped();
bool tailDrained();
uint32_t discardedTailObjects();
void release(); // after transport exit and storage finalization
uint16_t describe(BdqV2StreamDescriptor*,uint16_t capacity,uint16_t firstId);
}
