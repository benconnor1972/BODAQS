# r29: whole-run ordinary-control state and memory observations

Diagnostic-only continuation of r28 dffb7725c678d1975e0146f4c202ec7aa583fdf8.
Keep512-entry sample buffers, ordinary20 scheduling, priorities, pacing, storage
settings, four IMUs, ADC-off config and retained r27 master
d1e3b6ba5f3f81c2e77c3236b741f2d7757abdd0. Six-minute normal run and late
300-330s master export remain unchanged. No retry, loss report, control, ACK,
credit, authorization or sensor data behavior changes.

## Question and predictions

R28 delivered99.24% in its first source-sequence half versus87.25% in its second.
Its larger queues absorbed SD bursts, yet quiet sample admissions declined.
The late master snapshot spent2516/21676 exchanges on empty ordinary control
discovery. Before changing its20ms interval, distinguish longer pending requests,
partial/outgoing bypasses, idle/no-data fallbacks and actual memory degradation.

- Growing pending age with repeated operation IDs points to slow/stuck result
  completion; begin/matched/timeout counts and last opcode/page add context.
- More outgoing/partial/unadmitted observations indicate bypass work, not simply
  due discovery. Pending-not-due/idle observations indicate that actual fetches
  are still sent despite the ordinary eligibility snapshot not requesting them.
- Persistent falling sampled free heap or largest blocks supports an allocation
  or fragmentation hypothesis. Stable point samples weaken that hypothesis but
  cannot exclude transient peaks, unsampled leaks or non-memory resource loss.
- MOSI target mix reveals changed allocation of slots. Loss-report callbacks
  remain separately observed by the unchanged r26 timeline; repeated cumulative
  reports are not unique missing readings.

## Bounded observations and ownership

Only environment bodaqs_s3_mini_n4r2_imu_control_state enables new default-off
BODAQS_CONTROL_POLL_DIAGNOSTICS=1. It requires the existing timeline/ordinary20
profile. Separate acquisition and storage banks share the existing published
logger origin,36 x20s bins (12minutes), reset/retirement lifecycle and sticky
overflow convention. Their total is statically bounded10000bytes and charged
through existing recording reservation. Acquisition alone writes request/peer
and event state; storage alone writes memory samples. No cross-owner live-array
reads or new diagnostic locks/allocations. Final JSON reads only after the
existing matching completed acquisition/FLOW retirement proof. Wrong/absent
retirement produces unavailable, and storage samples freeze before summary I/O.

The acquisition owner publishes its four ordinary-exchange snapshots immediately
before the existing transport call. The manager counts the final actual MOSI
request after outgoing/ACK/bridge selection, before exchange and before updating
the ordinary fetch timestamp. Priority reason observations are mutually
exclusive: outgoing complete, partial result, unadmitted result, pending first
fetch, pending due, pending not due, ACK only, idle. These are state observations
at transmission, not a trace of every selector predicate invocation. Scanning
candidates is not counted as sending requests. Requests of other targets are
counted too; no received empty response is attributed to the current request in
the pipelined/full-duplex link. Per-node pending age uses unsigned millisecond
deltas and64-bit sums. First/last operation and last opcode/page are fetch-time
samples, meaningful with their counts/pending flags, not an exhaustive journal.

Ordinary begin events follow successful queueing. Matched events precede
clearing a correlated exchange, including matched error/receipt responses;
they do not independently assert successful operation completion. Timeouts
observe the existing ordinary timeout branch. Counts need not balance within a
bin: scopes cross edges and STOP/exclusion/cancellation can clear pending work
without either a matched response or timeout event.

At the first regular BDQ storage service in each bin, storage samples free and
largest internal8-bit heap and PSRAM using capability-specific SDK APIs. These
four calls occur once per20s, outside acquisition/SPI loops. The calls are
separate, non-atomic point samples, not session or boot low-water marks. The
sample tick is retained; no samples are invented for missed bins or host
composition tests. Capability-specific free values must not be added into a
purported whole-device RAM budget with static reservations.

## Artifacts and interpretation

New optional BDQ final-summary field control_poll_timeline version1; existing
file/wire versions and recording_timeline remain unchanged. No public function
signatures/config fields change. Decoder checks exact64-bit context, geometry,
array ranges, accounting and overflow. Missing memory points remain explicit.
Internal largest/free values may momentarily appear inconsistent because API
calls are not atomic; this alone is not rejected as corruption.

Validate actual classification/age/reset/overflow/concurrent owners and final
JSON, actual SDK-call adapter in the real storage pump, enabled/disabled complete
MOSI bytes/order through real ordinary scheduling including lost ACK/proof,
full selected four-node recording/STOP/repair/allocation and the default host
suite. Host heap API stand-ins test the adapter, not real target heap levels.
Physical diagnostic interference, actual heap availability and the causal source
of throughput decline remain to be measured. No100ms backoff or loss-report
suppression is included in this round.
