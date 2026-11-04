# Responsive recording storage worker (#165)

Implemented against approved design baseline `8e0c673` and integrated control
baseline `0139d69`. Scope: [#165](https://github.com/benconnor1972/BODAQS/issues/165),
the [acquisition contract](CAN-FD_Acquisition_Transport_Contract.md) and network
interview Q120–Q121. Physical qualification #175–#176 remains deferred.

## Ownership and behavior

On ESP32 a persistent `StorageTask` owns recording health/open/header, queue
consumption, writes/flushes, final summaries, close, sidecars and archives. Its
initial allocation is 12,288 stack bytes, priority 1, core 1. Stack headroom and
throughput remain unqualified. The sampler remains on core 0. The portable
`RecordingStorageWorker` publishes atomic commands, outstanding operations and
faults; the production `LoggerStorageSink` uses the existing writers. CSV, BDQ v1
and BDQ v2 encoders, sample IDs and timestamp formats are unchanged.

`StorageManager_startLog()` now acknowledges a queued start on ESP32, rather
than completed file opening. `LoggingManager::requestStart()` reports Pending
until readiness, then its loop enables acquisition. `start()` still returns true
only for completed acquisition startup. Stop/cancel can run during blocked open.

`StorageManager_stopLog()` queues finalization on the control task and returns.
Owner-only `StorageManager_drainQueuedSamples()` performs no I/O for control
callers. New observations report pending, ready and fault state. Stop disables
acquisition first. The controller feeds up to eight final sensor rows per pass
as queue space becomes available, then requests owner drain/close. Configuration
and control fences, sensor diagnostics and Wi-Fi suspension survive until I/O
quiesces. Once Stop is submitted, producers cannot touch queues being released.

The control loop independently checks outstanding I/O against **5,000 ms**.
Timeout reports **Storage unresponsive** and stops acquisition without waiting
for the worker. Confirmed write/finalization failure reports **Storage failure**.
These reasons appear in `LoggingManager::StopContext`. Pending/failed operations
are never reported clean by the controller, even if an end marker was written
before a blocked close. The worker is never killed, concurrently closed or
unmounted. Known failed sessions skip normal summaries/archives where possible.

There is no automatic restart or reuse of the failed file. After quiescence, an
explicit operator start runs a separate write/flush/close/read probe at
`/.bodaqs-storage-health`, verifies four bytes `42 44 51 A5`, removes the probe,
then opens a new session only on success. This verifies software-visible access,
not physical durability. Web/config/remount access is gated during pending I/O.
Deep sleep reports Storage busy and returns while I/O is pending; an operator
can request sleep again after finalization.

## Verification

TDD used the approved storage sink and lifecycle seams. The first tracer failed
because the worker interface did not exist, then passed the normal sequence.
Independent sink cases cover blocked write/close, the exact 4,999/5,000 ms
boundary, returned failure, failed health, explicit fresh start and 500 repeated
start/stop cycles against a concurrent persistent worker.

Commands, with `C:/msys64/ucrt64/bin` on PATH for compiler DLLs:

```text
C:/ti/ccs2101/ccs/utils/bin/gmake.exe -C firmware/test test CXX=C:/msys64/ucrt64/bin/g++.exe
python firmware/tools/test_storage_worker_runtime.py --compiler C:/msys64/ucrt64/bin/g++.exe
python firmware/tools/test_logging_start_runtime.py --async-storage --compiler C:/msys64/ucrt64/bin/g++.exe
pio run -d firmware -e bodaqs_s3_mini_n4r2 -j 4
```

The full logger host suite passed, including existing format/writer, acquisition,
configuration, startup and control/recovery regressions. The synchronous logging
fixture passed 133 checks. Its new mode compiles the **production ESP32 controller
branches** with the real portable worker and an independent sink: 29 checks pass
for pending open, readiness, Stop, cancellation, open/health failure, blocked-open
timeout, rejection of restart during I/O, fresh operator start, final rows waiting
for space, blocked close and returned writer failure. Both modes and the worker
fixture run in the Makefile. The A8 `bodaqs_s3_mini_n4r2` build passed.

No device probing, flashing, physical SD stalls/removal, bandwidth measurements,
stack-watermark checks or electrical/timing qualification were performed. Host
fixtures establish simulated control/ownership behavior; they do not establish
actual SD driver scheduling, storage durability or physical timing.
