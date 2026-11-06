# SPI execution controls, round 4

This logger-only bench revision follows [round 3](SPI_Integrity_Probe_Round3.md).
Master/common protocol, ADC commands/settings, normal firmware behavior, CRC and
acceptance/ACK rules remain unchanged. User flashing remains manual. Result
schema is `bodaqs.spi-probe.v4`; the analyzer also accepts v1/v2/v3.

## Evidence and predictions

Physical case 302 rejected 7136/15756 replies; all failures followed ADC traffic.
6814 followed START; 0/2815 followed master traffic. Four retained failures had
byte zero replaced with 00; restoring 53 offline made the stored CRC match.
Padding ADC transmit buffers did not resolve this. Cases 303 and 304 were clean:
12334 deselected-shape replies and 11930 selected-sequence replies respectively.
Case 304 included 11143 replies immediately following real ADC operations.
These controls had no workers and lower ADC traffic, and paused master polling
during conversion waits. They cannot distinguish concurrency from rate/timing.

Predictions to test, without claiming a root cause:

1. If task/core handover matters, changing only the worker core changes failures.
2. If density matters, pacing changes failures across execution contexts.
3. If overlapping ADC activity matters, a one-ADC worker control changes failures.
4. If one-owner scheduling helps, independent owner conversions are cleaner at
   comparable observed ADC and master rates. Polling/interrupt/cache differences
   remain, so this would not prove a defective mutex or cross-core HAL operation.

## Command and lifecycle

Existing seven/nine-token commands retain their meaning and restore default
worker mask 3, core 0 and no additional pacing. New modes require twelve tokens:

```text
case ID workers FRAME HZ NODES MS legacy START_INTERVAL ADC_MASK ADC_CORE CYCLE_US
case ID owner   FRAME HZ NODES MS legacy START_INTERVAL ADC_MASK ADC_CORE CYCLE_US
```

`ADC_MASK` 1 selects ADC0/CS47, 2 selects ADC1/CS21, 3 both. `ADC_CORE` is 0 or 1.
For owner mode it must equal the actual Arduino owner core (1 on this build).
`CYCLE_US` is zero (no extra pacing), or 1500..20000 microseconds minimum cycle
interval. A late cycle starts from now; neither mode catches up missed cycles.
Worker pacing sleeps one RTOS tick at a time and can overshoot. It changes no
ADC sample-rate register. Core/mask/period are immutable until complete shutdown.

Workers mode uses the actual existing ADC tasks, interrupt registration, DRDY
notifications, acquisition and cache publication, with requested core/mask and
optional pacing. It performs no row reads. Masked ADCs receive no warmup or worker
start. Complete requires timed reads on every enabled ADC and no acquisition
failure or ready timeout. Original mixed mode remains the unchanged row workload.

Owner mode starts no workers or interrupts. It maintains separate WREG/START/
RDATA state for each enabled ADC, alternates eligible operations, and polls real
DRDY with the inherited 6000 us timeout. At most one ADC operation runs per owner
iteration, followed by master tick even when neither ADC is ready. ADC conversions
can overlap; master polling continues during waits. Samples are discarded, with
no cache publication or row reads. Complete requires reads on every enabled ADC.
An owner stall longer than the readiness deadline fails closed rather than
asserting physical conversion failure. A final partial cycle is allowed.

Rail checks, finite duration, serial STOP, confirmed master STOP, monotonic case
IDs and reboot-required blocking after incomplete shutdown remain in force.
STOP during pacing/waits is bounded by the existing worker shutdown path. A
single-shot conversion may finish after STOP; no acquisition loop remains.

## Observations and interpretation

The top-level `execution` object records requested `adc_mask`, `adc_core`,
`cycle_us`, actual `owner_core`, and a separate software traffic window with
64-bit start/end times. The window opens after worker startup and closes before
worker/master STOP. Under the existing probe spinlock it records each participant's
successful transfers, lock failures, observed caller core bitmask, and successful
5/1/4-byte operation counts. It observes completion bookkeeping after bus release;
a boundary transaction can straddle the window. It is not pad-edge timing.
Existing all-scope counters still include warmup/startup/shutdown.

Core bitmask 1 means core0, 2 core1; this is measured in caller tasks, not inferred
from requested affinity. `sequence` is active for shape/selected/owner, inactive
for workers. `worker_start_requested` is true for adc/mixed/workers after startup
was attempted. All retained raw frames and previous-operation metadata persist.

Analyzer reports window transfer/read rates and requested settings separately.
Compare observed per-ADC operation rates, master request intervals, operation
distributions and failure counts. Equal requested periods do not establish equal
rates or bursts. Neither new mode measures row freshness or supports admission.
Existing CAN/SPI drop counters remain independent evidence of receive pressure.

## Manual sequence

Use the new bundle README and a fresh serial capture, verify v4 identity and idle
status between cases, and report each result before advancing. All frame/clock/
CRC/master pacing choices stay at 128 bytes, requested 8 MHz, legacy, 500 us.

| ID | mode | mask | core | cycle us | purpose |
|---|---|---:|---:|---:|---|
| 400 | adc | default | default | 0 | ADC baseline |
| 401 | bulk | default | default | 0 | bulk baseline |
| 402 | mixed | default | default | 0 | reproduce original worker/row condition |
| 403 | workers | 3 | 0 | 0 | remove row reads only |
| 404 | workers | 3 | 1 | 0 | change worker affinity only |
| 405 | workers | 3 | 0 | 5000 | reduce worker traffic |
| 406 | owner | 3 | 1 | 5000 | compare observed rates with paced workers |
| 407 | workers | 3 | 1 | 5000 | paced workers on owner core |
| 408 | workers | 1 | 0 | 0 | ADC0 alone |
| 409 | workers | 2 | 0 | 0 | ADC1 alone |

Do not automate the whole matrix. Adjust later pacing only after inspecting
observed rates; use a new increasing ID. A clean control is not a physical fix.

Host tests execute real controller, worker, bus, codec and engine bodies against
simulated peripherals/RTOS. They verify command routing, affinity arguments,
window scope, masks, paced rates, independent conversions, master polling during
waits, timeout/STOP and restart/default reset. They cannot emulate ESP32 dual-core
scheduling, peripheral state, electrical corruption or physical DRDY deadlines.
Target builds check both probe and normal environments. Physical reproduction
and matched-load conclusions remain manual evidence debt.
