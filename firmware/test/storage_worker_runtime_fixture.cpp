#include "RecordingStorageWorker.h"
#include <cassert>
#include <atomic>
#include <thread>
#include <cstdio>
struct Sink : RecordingStorageSink {
 bool start() override { return true; }
 bool service() override {
   entered.store(true);
   while (block.load()) std::this_thread::yield();
   ++rows; return !fail;
 }
 bool stop(bool clean) override {
   entered.store(true);
   while (block.load()) std::this_thread::yield();
   finalized = clean; ++closes; return !fail;
 }
 bool healthCheck() override { ++probes; return healthy; }
 std::atomic<bool> block{false}, entered{false};
 bool fail = false, healthy = true;
 int rows = 0, closes = 0, probes = 0; bool finalized = false;
};
int main() {
 Sink sink; RecordingStorageWorker worker(sink);
 assert(worker.requestStart()); worker.step(10);
 assert(worker.recording()); worker.step(20);
 assert(sink.rows == 1); worker.requestStop(); worker.step(30);
 assert(!worker.pending() && sink.finalized);
 // Blocked write: control can stop and observe the deadline without waiting.
 assert(worker.requestStart()); worker.step(100);
 sink.block = true; sink.entered = false;
 std::thread io([&] { worker.step(200); });
 while (!sink.entered.load()) std::this_thread::yield();
 worker.poll(5199); assert(worker.fault() == RecordingStorageWorker::Fault::None);
 worker.requestStop(); worker.poll(5200);
 assert(worker.fault() == RecordingStorageWorker::Fault::Unresponsive);
 assert(worker.pending() && sink.closes == 1);
 sink.block = false; io.join(); worker.step(5300);
 assert(!worker.pending() && !sink.finalized && sink.closes == 2);
 // Returning to idle must not automatically recover or resume the old file.
 worker.step(5400); assert(sink.probes == 2);
 sink.healthy = false; assert(worker.requestStart()); worker.step(5500);
 assert(!worker.pending() && worker.fault() != RecordingStorageWorker::Fault::None);
 sink.healthy = true; assert(worker.requestStart()); worker.step(5600);
 assert(worker.recording() && sink.probes == 4);
 sink.fail = true; worker.step(5700);
 assert(worker.fault() == RecordingStorageWorker::Fault::Failure);
 worker.requestStop(); worker.step(5800); assert(!worker.pending() && !sink.finalized);
 // Even close remains owned by the worker while it is blocked.
 sink.fail = false; assert(worker.requestStart()); worker.step(6000);
 worker.requestStop(); sink.block = true; sink.entered = false;
 std::thread close([&] { worker.step(6100); });
 while (!sink.entered.load()) std::this_thread::yield();
 worker.poll(11100); assert(worker.pending());
 assert(worker.fault() == RecordingStorageWorker::Fault::Unresponsive);
 sink.block = false; close.join();
 assert(!worker.pending() && worker.fault() == RecordingStorageWorker::Fault::Unresponsive);
 // Repeated starts/stops against a persistent task exercise command publication.
 Sink concurrentSink; RecordingStorageWorker concurrent(concurrentSink);
 std::atomic<bool> quit{false};
 std::thread task([&] { while (!quit.load()) { concurrent.step(1); std::this_thread::yield(); } });
 for (int i = 0; i < 500; ++i) {
   assert(concurrent.requestStart());
   while (!concurrent.recording()) std::this_thread::yield();
   assert(concurrent.fault() == RecordingStorageWorker::Fault::None);
   concurrent.requestStop();
   while (concurrent.pending()) std::this_thread::yield();
 }
 quit = true; task.join();
 assert(concurrentSink.closes == 500 && concurrentSink.probes == 500);
 puts("Storage worker: normal, blocked write/close, Stop, failure, health-gated restart passed");
}
