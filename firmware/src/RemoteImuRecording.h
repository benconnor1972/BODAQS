#pragma once
#include <stdint.h>
struct LoggerConfig;
struct BdqV2StreamDescriptor;
namespace RemoteImuRecording {
// Allocation, reconciliation and lifecycle startup run while local acquisition
// is stopped. This first recorder admits one configured remote IMU.
bool configure(const LoggerConfig&);
bool configured();
bool prepared();
bool recording();
bool failed();
void start();
void stop();
void service(); // main-loop orchestration, never transport/storage progress
bool stopped();
bool tailDrained();
uint32_t discardedTailObjects();
void release(); // after transport exit and storage finalization
uint16_t describe(BdqV2StreamDescriptor*,uint16_t capacity,uint16_t firstId);
}
