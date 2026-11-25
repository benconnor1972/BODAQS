# Local ADC and shared SPI look-ahead scheduling

16 November 2026. Focused primary-source research and conceptual recommendations;
no firmware change or schedulability claim.

## Recommendation

Try a small application-level bus admission rule before considering a new RTOS
scheduler: publish the next ADC service windows, check each CAN transaction
against them, and use the conversion intervals for CAN work. Link ADC acquisition
to the 2 ms row cadence so that useful conversions have predictable deadlines.
Reserve CAN service as well: a guard that preserves analog freshness while
eventually exhausting CAN retention is not an improvement.

This builds on [the existing mixed-load research](Mixed_Load_Acquisition_Primary_Research.md).
The timings below are supplied experiment context, not independently verified
WCETs: a 512-byte CAN-master exchange at 16 MHz takes 256 us on the wire,
about 340 us in the HAL and about 400 us while holding the shared mutex. Each
ADS1220 uses approximately 1 ms of off-bus conversion, plus 6-byte setup/start
and 4-byte read exchanges at 1 MHz. There are two ADCs, latest-value caches,
500 rows/s and approximately 690 conversions/s per ADC. These assumptions
describe one active channel per ADC; scanning more channels changes the budget.

## What the literature supports

Jeffay, Stanat and Martel analyze nonpreemptive periodic/sporadic work and show
that utilization alone is insufficient. Their EDF result assumes independent
jobs on one processor, deadlines equal to recurrence periods, and no inserted
idle time. It is not a proof for this multi-stage ADC/dual-core logger. Their
distinction between unspecified and specified release phases also matters here:
predictable phases are information a bus policy can exploit. [Author-hosted
1991 paper, Sections 2, 4 and 5](https://www.cs.unc.edu/~jeffay/papers/RTSS-91.pdf).

Davis, Tindell and Burns study reclaiming time for soft work while preserving
hard periodic/sporadic deadlines under fixed-priority preemptive scheduling.
This supports considering slack reclamation without replacing fixed priorities.
The university publication record's abstract was checked; its algorithm is not
directly applied to this nonpreemptive shared bus. [University of York publication
record, 1993](https://pure.york.ac.uk/portal/en/publications/scheduling-slack-time-in-fixed-priority-pre-emptive-systems/).

The following admission and phasing proposals are engineering deductions from
the stated logger model, not algorithms proved by those papers.

## Small opportunities, in order

1. **Stop producing avoidable overwritten conversions.** Target one completed
   acquisition for each intended row, with an explicit acquisition epoch and
   cache generation. Reducing 690 to 500 conversions/s is 27.5% fewer ADC cycles.
   For two ADCs and the stated 10 bytes/cycle, the raw wire saving is only
   `2 * 190 * 10 * 8 / 1,000,000 = 3.04%` of bus time; removed driver, wake-up and
   contention overhead may matter more. This is a candidate saving, not a
   demonstrated gain: phase errors could reduce freshness if simply rate-limited.
   Surplus conversions currently provide some jitter insurance; replace that
   insurance with measured phase/guard margins before reducing the rate.

2. **Plan backward from the row.** Choose a completion target before row `R`.
   Reserve read/cache publication before that target; place setup/start earlier
   by conversion time plus dispatch and conversion uncertainty. Protect both
   setup and read windows. Protecting only the row instant misses the earlier
   latest-start constraint. Release the mutex throughout conversion. TI defines
   single-shot conversion time from START/SYNC to DRDY and requires additional
   oscillator wake-up allowance with the internal oscillator. Use DRDY when
   available and include oscillator tolerance; do not treat nominal 1 ms as a
   worst-case bound. [TI ADS1220 datasheet, Output Data Rate and Table 8-4](https://www.ti.com/lit/ds/symlink/ads1220.pdf).

3. **Stagger the short bus actions.** Offset ADC0 and ADC1 setup/read windows
   enough to avoid simultaneous requests, while letting their conversions
   overlap. A whole 1 ms offset is unnecessary if tighter inter-sensor alignment
   matters. Use the same row epoch for both. Existing cache `acquiredUs` denotes
   read/publication completion, not the physical measurement instant; preserve
   that meaning and clarify any additional conversion timing evidence before
   making stronger alignment claims. An illustrative phase must be selected from measured service times;
   an exact schedule is not established by the present evidence.

4. **Admit one CAN transaction at a time.** If `S` is the next reserved ADC bus
   window start, start a CAN exchange only when
   `now + C_can_bound + dispatch_margin <= S`. If the ADC completion deadline is
   `D`, derive `S` from `D` minus all reserved ADC service/publication work and
   jitter; do not compare the CAN duration directly with `D`. Check after taking
   the mutex and immediately before committing the exchange, using coherent
   shared reservation state. Checking before a mutex wait creates a race. Keep
   the existing master minimum-start spacing as an additional eligibility rule.
   During its released-mutex wait, reevaluate time and reservations. Check every
   exchange in an eight-service burst rather than admitting the entire burst.

5. **Reclaim actual slack.** When an ADC action completes early, move on to CAN
   work that fits before the next reservation. If nothing fits, block until a
   relevant event/window rather than polling continuously. A small shared-bus
   owner or admission layer can do this while FreeRTOS continues using fixed
   task priorities. Ready-queue EDF by itself cannot prevent an already-started
   400 us transaction from blocking a newly released ADC action.

## CAN must have a deadline too

Bound maximum CAN service gaps and reserve enough useful drain throughput for
the sustained arrival rate, retries, control traffic and burst recovery. Use the
earliest node/master evidence-expiry or overflow deadline, not merely host queue
occupancy. Repeated ADC reservations cannot indefinitely defer CAN. If a CAN
service requirement conflicts with an analog window, choose an explicit missed
analog epoch/reuse indication when that is the permitted degradation, rather
than allowing an unreported retention failure. Preserve existing sequence,
timestamp, loss and replay semantics.
Startup/configuration and failure metadata can be required to interpret the
recording, so CAN traffic cannot all be classified as expendable background work.

Le Boudec and Thiran bound backlog using an arrival envelope and a guaranteed
service curve. For `alpha(t)=b+r*t`, `beta(t)=R*max(0,t-L)` and `R>=r`, backlog is
bounded by `b+r*L`. Thus both a sustained service rate and a maximum latency
matter. The envelope must hold over all relevant intervals; average throughput
does not supply it. [Authors' Network Calculus book, Section 1.4](https://leboudec.github.io/netcal/latex/netCalBook.pdf).

For this logger, apply that reasoning separately to each finite retention stage.
Without known arrival bursts, capacity and service guarantees, a watchdog-style
maximum-gap rule is a useful measured safeguard but cannot prove no loss.

## Timer choice and evidence threshold

`vTaskDelay(1)` is tick-relative and phase-dependent, rather than a precise
microsecond appointment. `xTaskDelayUntil` prevents relative-period drift but is
still tick-resolution. [ESP-IDF v4.4.7 S3 FreeRTOS API](https://docs.espressif.com/projects/esp-idf/en/v4.4.7/esp32s3/api-reference/system/freertos.html).
`esp_timer` offers microsecond time resolution, but task-dispatched callbacks can
be delayed by higher-priority work; keep callbacks short and notify workers.
Timer resolution is not a dispatch-latency guarantee. [ESP-IDF v4.4.7 S3 timer
guide](https://docs.espressif.com/projects/esp-idf/en/v4.4.7/esp32s3/api-reference/system/esp_timer.html).
Affinity affects which ready tasks each core can execute, while both cores still
share the SPI exclusion interval. Pinning is therefore not a substitute for
transaction admission. [ESP-IDF v4.4.7 S3 SMP guide](https://docs.espressif.com/projects/esp-idf/en/v4.4.7/esp32s3/api-guides/freertos-smp.html).

Start with conservative measured guards and call the result a heuristic.
Approximately 400 us mutex occupancy is not a demonstrated upper bound. A hard
guarantee additionally needs bounded CPU/interrupt interference, mutex ownership,
driver occupancy, timer/worker dispatch, conversion timing, all bus users,
reservation-update races and CAN arrival/service demand. Test guard overruns,
ADC start/read lateness and age tails, fresh uses per row, CAN useful drain rate,
maximum service gap, retention high-water marks and explicit loss/reuse counts
under simultaneous recording and control traffic. Compare identical workloads
with unpinned baseline, phase control, then phase control plus admission. This
documentation-only research requires no firmware build; timing validation still
requires the actual board, firmware and sustained mixed-load runs.
