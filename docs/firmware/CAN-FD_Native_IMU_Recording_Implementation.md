# One-node native IMU recording (#169)

Software implementation and validation, 5 November 2026, based on verified
integration `89b291e`. The authoritative requirements remain
[the acquisition contract](CAN-FD_Acquisition_Transport_Contract.md),
[network protocol](CAN-FD_Network_Protocol.md), and
[leased lifecycle](CAN-FD_Acquisition_Lifecycle_Implementation.md).
This evidence does not qualify physical association, timing or capacity.

## Production path

The node now installs `bodaqs_node_acquisition_backend` in the existing leased
lifecycle. Configuration and acquisition share the physical SPI owner; backend
polling continues after an individual command completes. `imu_capture.c` extends
the nominal 1 MHz TIMA0 counter, retaining capture ordinals and rejecting capture
overflow or ambiguous service blackouts. PREPARE does not restart that counter.
Lifecycle challenge issuance uses the same phase through `set_clock`.

`imu_spi.c` owns bounded 4 MHz sensor DMA, including the command byte and up to
96 seven-byte tagged FIFO words. It excludes command-phase RX, waits for the
actual RX count and SPI idle, and cancels both channels on failure. INT1 supplies
acceleration DRDY captures and INT2 the FIFO watermark; the service also polls
at 5 ms. FIFO status after DMA is checked before held words are published.

Every preparation configures and verifies the runtime register image, explicitly
resets and observes the separate sensor timestamp counter, and obtains a
no-edge FIFO-enable fence. It observes 70 ms settling plus at least 270 gyro
and ten acceleration discards, including warm preparations. Slot tag counters,
engine pairing, timestamp progression, capture order and measured cadence must
agree. Missing or ambiguous association excludes; no nominal capture is invented.
START takes the first subsequent complete slot as sequence zero of a fresh
source epoch. There is no pre-roll. Local rational models use observed capture
intervals and retain unknown finite uncertainty explicitly.

The bounded node CAN queue retains startup/boundary/model/anchor evidence before
dependent compact packets; hardware backpressure does not block FIFO service.
STOP shuts FIFO/timestamp production down while preserving the configured engine
profile. FENCE waits for software and hardware TX retirement. See the exact
adapter fixtures and pin/clock details in
[`node/test/README.md`](../../firmware/can-fd/node/test/README.md).

The master retains 96 ingress records per node behind each selected immutable
batch. A class/boot/ordinal-high change seals a head; evidence is immediately
eligible and partial sample heads retain their original 20 ms fill age. Full
retention drops newer receptions, preserving the selected head and raw ISR
ordinal. Membership/current boot and existing anchor/epoch gates remain binding.
Fencing retires both selected and queued data. These allocations are concrete
buffers, not a four-node service-envelope proof.

## Logger and persistence

`RemoteImuRecording` reconciles and allocates one remote IMU before preparation,
obtains a fresh immutable prepared snapshot, and starts only after the independent
storage worker has written the header/catalog. The UI shows Preparing, Recording
and Finalizing. An unavailable remote is explicitly excluded while healthy local
recording remains possible. Multiple requested remote IMUs are explicitly
unavailable in this slice; four-node admission belongs to #173.

The remote preparation/start gate has a ten-second deadline. STOP is terminal,
and its five-second tail deadline is captured at the original operator request;
repeated STOP and main-loop delay do not extend it. A closed/active atomic gate
prevents any producer callback from writing to a closing file. Later retained
objects are ACKed as discarded and counted. Storage can finalize after this
cutoff while conservative membership cleanup continues. Failed cleanup retains
ownership/configuration locking rather than claiming a completed fence or
automatically rejoining. The final summary separately records exclusion, cleanup
completion, discarded tail objects and conservative `unknown`/`incomplete` source
tail coverage; a clean storage close never proves a complete source tail.

The control task services bounded groups of eight separately locked SPI slots,
releasing the mutex and preserving the inactive-CS interval between slots.
Protected replies take priority while awaiting a lease/STOP result. Active
backlog drains without imposing the 50 Hz empty-poll ceiling on every full head.
This removes the former one-slot-per-RTOS-tick cap; actual software costs and ADC
service opportunities still require qualification. STOP can supersede partially
received renewal results without pinning an object the master has retired.

`RemoteImuStream` expands compact axes into the accepted 28-byte payload and
timing messages into 224-byte companions. Source segments, clock epochs, model
origins/applicability, raw presence/association masks, reception ordinals and
boundary validity stay distinct. Unknown alignment does not prevent recording.
Missing essential definitions and conflicting origins fail explicitly.
Bounded unmatched anchors may arrive before their canonical models.

The catalog freezes UID/address/boot, decimal-string identities, the complete
stopped admission descriptor and known/historical masks, profile/scaling,
mounting/calibration/quaternion, payload schemas and separate physical clock
IDs. It does not call stopped configuration proof runtime capture proof.
All companion channels use their exact contract offsets. The writer/catalog
capacity is 37 streams, preserving primary + 32 logical sensors + four companions.

Sample queues retain an evidence serial alongside each exact 28-byte record.
The writer calls a stream acknowledgement only after its complete chunk reaches
the sink; dequeuing evidence alone cannot make dependent samples writable.
Expanded queued records retain this dependency after model-table retirement.
The storage worker remains the sole file writer. BMI layouts and parsing remain
unchanged. See [the independent raw reader](../analysis/CAN_IMU_Raw_Reader.md).

## Software evidence

- Node adapter fixtures compile the actual SPI/capture/acquisition files against
  a narrow TI boundary. Literal FIFO words and independent capture/DMA inputs
  cover cold/warm settling, signed axes, rollover, first/final boundaries,
  missing captures, malformed tags/timestamps, stale DMA IRQ, post-drain overrun,
  six-ms CAN backpressure and actual hardware-TX fence gating.
- Common host tests cover immutable retention, membership, fragments and leased
  lifecycle. Logger runtime regressions cover existing configuration/storage,
  four independent lifecycle fixtures and one-node production orchestration.
  The coordinator test caught and now covers an abandoned configuration snapshot
  pin, protected reply starvation, STOP superseding a partial renewal reply,
  and RELEASE preceding physical master retirement.
- `test_node_master_bdq_runtime.py` compiles/runs the actual node adapter, routes
  its CAN output through the actual master retention/fragment codec and native
  writer, then independently parses BDQ in Python. It verifies 65 samples with
  literal signed axes, native ticks, segment identity, five evidence events,
  masks, original reception order and evidence chunks before sample chunks.
  Separate literal vectors and torn predecessor tests prevent a writer/reader
  implementation from serving as its own expected-value oracle.
- Explicit G3507 node and G3518 master TI Arm Clang/SDK 2.11 builds pass. Node:
  FLASH 36,792 bytes, SRAM 10,819 including reserved stack. Master: FLASH 35,544,
  SRAM bank 0 49,609 including reserved stack; bank 1 remains unused.
- Explicit A8 PlatformIO `bodaqs_s3_mini_n4r2` builds: static RAM 264,308 bytes,
  flash 2,008,825 bytes. The complete firmware host target, all twelve common
  test binaries and the three physical-adapter binaries pass. The complete
  analysis suite reports 577 passed and one skipped. Static maps do not prove
  runtime heap/PSRAM/stack headroom; host timing is not physical qualification.

## Follow-on seams and physical debt

#170 supplies synchronized master/node observations, clock bridge and analysis
alignment. Master reception ticks currently retain their explicitly quantized
millisecond-derived clock; they are not a precision capture claim. #171 owns
broader bounded loss/recovery and continuity handling. #172 owns comprehensive
link/restart cleanup and unavailable-context recovery. #173 must account for
all queue/descriptor/transport/task allocation, select compatible CAN profiles,
and prove complete admission/service budgets. The existing 500 kbit/s / 2 Mbit/s
CAN bring-up profile is preserved for this one-node implementation.

The 96-word watermark/burst, 5 ms fallback, 10 ms first-free, 1 ms repeat gap,
25 us master rearm, 100 us mutex hold and 10 us inter-node target remain
unqualified physical targets. No firmware was flashed. FIFO/DRDY electrical
association, native capture precision, sensor/filter phase, SPI/DMA/SYNC timing,
actual throughput, stack watermarks and debugger/reset/disconnect fault tests
remain deferred to #175/#176. Existing explained FRONT_FAULT telemetry is untouched.
