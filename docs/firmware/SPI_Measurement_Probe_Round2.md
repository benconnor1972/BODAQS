# SPI probe diagnostic round 2

Status: implementation scope authorized by the user after the first comparison
matrix. This is a bench diagnostic revision, not production implementation or a
new capacity pass. Original artifacts and measurements remain unchanged.

The first ADC-only case produced 5000 fresh rows/channel in 10 seconds. All six
bulk cases decoded without errors; all six mixed cases failed reply decoding
and fresh-per-row criteria. Best observed bulk service was 46.17 kB/s. Four
nominal 3.33 kHz six-axis IMUs need roughly 160 kB/s of raw values, or 200 kB/s
with the agreed 1.25x drain margin, before additional metadata. Correct decoding
alone does not demonstrate adequate service.

## Required behavior

1. Preserve the existing instrumented behavior as an explicit `legacy` CRC
   control. Add `cached` expected-CRC mode, selected before a case and immutable
   until STOP. Cache only the deterministic expected checksum, once per node
   object. Keep wire CRC, exact fragment bytes, identity, whole-object CRC, RAM
   acceptance and ACK/STOP safety. No multiple outstanding objects or live fallback.
2. Classify the first failed decoder check without executing a second decode or
   changing validation order. Keep at most four complete failed replies per case
   in fixed RAM, including the request identity and transaction context. Retain
   omitted-sample counts. Print only after workers/transport have stopped.
3. Capture the preceding shared-bus participant and CS timestamps while owning
   the actual bus mutex. ADC transactions must be visible without running probe
   transport from ADC workers. Timestamp scope is software, not pad edges. Count
   decoded responses and failures by preceding participant as well as retaining
   samples; first samples alone do not establish a distribution.
4. Measure validation, expected-checksum computation, active transport iteration
   and successive master request intervals. Export master request processing,
   CS retirement/rearm and prepared-reply publication-to-swap observations. Keep
   scope, cumulative counters, boot maxima and clock-invalid state distinct.
5. Add a minimum master request start interval, 0 (no added pacing) through
   5000 us, in addition to the unchanged 25 us master inter-CS minimum. Waiting
   must not hold the bus mutex or block row scheduling. Report actual intervals;
   a configured interval is not proof of matched offered traffic.
6. Add `switch`: bulk transport with a controlled four-byte 1 MHz/mode1 clock
   burst between requests while all registered board SPI CS lines are high.
   Use the production SPI driver and mutex. No ADC conversions/workers run in
   this mode; record it as a synthetic control, never as an ADC/throughput pass.
   Record this unselected operation as participant -2; unknown participant is -1.
7. Give the probe build an identity derived from source revision/content, which
   changes when another compiled firmware source changes. A cached compile-date
   string is insufficient. Include the identity in ready, status and case output.
8. Preserve the ADC GPIO-startup mutex correction, worker/ISR ownership, immutable
   tokens, bounded startup/STOP, finite case IDs and known-data integrity tests.
   All instrumentation and new controls remain guarded by BODAQS_SPI_PROBE.

## Interfaces

Wire version1 and physical layouts stay unchanged. STATS page2 is additive and
requires the matching diagnostic master image. Page0 and page1 stay compatible.

The common codec adds `BodaqsSpiProbeDecodeResult` and
`bodaqs_spi_probe_decode_result(wire,length,frame)`. Result order/numbers:
0 OK, 1 ARGUMENT, 2 FRAME_SIZE, 3 MAGIC, 4 VERSION, 5 PROFILE,
6 PAYLOAD_LENGTH, 7 CRC, 8 PADDING; COUNT=9. Existing bool decode remains a wrapper
with identical accepted/rejected frames. Guard sizes before accessing bytes.

Engine field `diagnostic_stats[10]` supplies STATS page2:

|Index|Meaning|Normalization|
|---:|---|---|
|0|process_calls|uint32 counter delta|
|1|process_total_us, low32|uint32 counter delta|
|2|process_max_us|boot maximum endpoints, never subtract|
|3|boundary_calls|uint32 counter delta|
|4|retire_total_us, low32|uint32 counter delta|
|5|retire_max_us|boot maximum endpoints, never subtract|
|6|publish_calls|uint32 counter delta|
|7|publish_wait_total_us, low32|uint32 counter delta|
|8|publish_wait_max_us|boot maximum endpoints, never subtract|
|9|timing_invalid|sticky endpoint state, never subtract|

Process spans main request processing; retirement spans the accepted software CS
boundary through DMA rearm; publication wait spans fully prepared publication to
the software boundary that swaps it. They may overlap and cannot be summed into
a physical bound. Take coherent snapshots and keep ISR-owned fields separate
from main-owned fields. Do not reset boot counters during a case.

Existing seven-token commands remain supported, with legacy CRC/no extra pacing.
Extended commands are:

```text
case ID adc|bulk|mixed|switch FRAME HZ NODES DURATION_MS legacy|cached START_INTERVAL_US
```

All-mode IDs remain strictly increasing during boot, including failed starts.
Ready/status/error/case output uses `bodaqs.spi-probe.v2`; the analyzer retains
support for historical v1 captures. The v2 profile adds `crc_mode` and
`start_interval_us`. Old metadata/counter scopes remain explicit.

The v2 case adds `diagnostics`:

- `decode_counts`: nine counters ordered as the decoder enum; counts successful
  decode calls separately from each first rejection reason. Wire errors equal
  the sum of indices1..8; transfer failures do not invoke decoding.
- `failure_samples`: at most four entries with numeric `reason`1..8, `slot`,
  `frame_bytes`, complete `rx_hex`, decoded request identity fields, and `bus`
  containing `sequence`, `cs`, `previous_valid`, `previous_cs`,
  `previous_release_us`, `cs_assert_us`, `cs_release_us`. Raw timestamps are
  uint32 microseconds; compute intervals modulo uint32. Zero is a valid time.
- `failure_samples_omitted`: rejected frames not retained.
- `by_previous_cs`: entries `{cs,responses,decode_failures}`, including -1/-2
  as needed. Responses count successful decodes; failures count first rejections.
  Their sum covers all actual decode calls. Failure fractions use both counts
  in the denominator.
- `timing`: TimingSummary objects `validate`, `expected_crc`, `iteration`,
  `request_interval`; `expected_crc_calls` equals expected_crc.count.
- `pacing_deferred`, `switch_transfers`, `switch_failures`: nonnegative counts.

`master` additionally contains `diagnostic_measured`, `diagnostic_before[10]`,
`diagnostic_after[10]`. Unsupported/failed snapshots remain unknown. The result
labels master component timing as software observations when measured; it never
claims physical rearm margin. Report consumers preserve maxima and flag states
separately from counter deltas. Diagnostic controls/paced cases never become a
production capacity/admission pass. CAN servicing stays excluded and its observed
losses remain visible with that scope; do not silently relabel them as zero.

## Initial manual sequence

Both logger and master are updated manually; the node is unchanged. Use raw
115200-baud capture, one command at a time, checking ready/idle between cases.
Predeclare 10 seconds. First establish ADC, bulk and mixed controls at128/8:

```text
case 200 adc 128 8000000 4 10000 legacy 0
case 201 bulk 128 8000000 4 10000 legacy 0
case 202 mixed 128 8000000 4 10000 legacy 0
```

Inspect failure reasons/samples before proceeding. Subsequent controls:

```text
case 203 bulk 128 8000000 4 10000 legacy 500
case 204 switch 128 8000000 4 10000 legacy 500
case 205 mixed 128 8000000 4 10000 legacy 500
case 206 bulk 128 8000000 4 10000 cached 0
case 207 mixed 128 8000000 4 10000 cached 0
```

Mode-switch clocks are a control for shared signals/settings, not a reproduction
of ADC conversion/worker scheduling. Added gaps change traffic; compare actual
request intervals rather than assuming equivalent load. Faster cached validation
also changes pacing. Diagnose reproducible integrity failures first; fresh ADC
service and sustained useful drain remain separate gates. No profile is selected
for production by this sequence. Optional external clock/CS captures retain their
instrumentation identity and measured scope.

## Validation and completion

Use approved public codec/master adapter, shared bus/ADC lifecycle and serial
command/result/analyzer seams. Add independent worked malformed-frame vectors,
same-mutex context/interleaving checks, bounded capture saturation/reset, per-object
CRC cache turnover, pacing/row scheduling, mode-switch deselection and explicit
unknown/state handling. Preserve actual Arduino GPIO startup red/green coverage.
Fresh boundary review precedes dependency use and final packaging. Build normal
and probe logger/master targets, pin source and artifact hashes, retain the old
bundles, and deliver new manual-flash images, analyzer and runbook. No remote
tracker changes, device probes or flashing are authorized in this round.
