# ADS1220 setup cost improvement

Implemented after the first real single-IMU recording milestone. Controlled SD
stall tests remain deferred; this change does not expand IMU admission or change
the selected master/node firmware.

Physical status (10 November 2026): the WREG-only r1 candidate failed.
`261110_091939.bdq` matches build08:28:23; each ADC made904 attempts with904
timeouts and zero successful readings. The same-format baseline control
`261110_093302.bdq` matches the original build08:31:00; each ADC completed18706
acquisitions with zero failures/timeouts. Across12629 rows, ADC0 reused10 and
ADC1 reused3, with no no-sample rows. This is strong evidence to retain explicit
START; it does not establish the exact silicon/protocol reason WREG-only failed.
The r2 implementation below restores START in a combined transaction. Host
validation does not establish its physical success or rate improvement.

## Conversion trigger

Previously each conversion used three shared-SPI transactions: full four-register
WREG (5 bytes), START (1 byte), then RDATA (4 bytes) after readiness. The driver
now sends `43 reg0 reg1 reg2 reg3 08` in one six-byte CS span, waits for readiness,
then performs the same four-byte RDATA transaction. This reduces three SPI
transactions to two, retaining all10 wire bytes and explicit START. It removes
one mutex acquisition, CS cycle and SPI-driver setup per conversion. It does not
establish a percentage improvement in conversion rate, CPU use or mixed throughput.

See TI [ADS1220 datasheet](https://www.ti.com/lit/ds/symlink/ads1220.pdf),
SBAS501D, sections8.5.3.2,8.5.3.6 and8.5.5. WREG consumes its declared payload
before the following byte is decoded as START. Register one retains CM=0. The complete
four-register write remains before every conversion, preserving restoration of
mux, gain, rate and reference after an ADC-only reset. The considered software
register cache was rejected because successful SPI transfer does not prove the
ADC retained its settings across a power/reset event.

Both asynchronous worker/live reads and synchronous scans use the same trigger.
The worker clears the previous ready notification **before the combined transfer**, then waits
using the existing level/notification check. Clearing after the combined transfer could discard
the new completion. Reads retain existing scaling, row-cache/freshness semantics,
rate selection, SPI settings and log format. No continuous-conversion mode or
new admission margin is introduced.

The regression fixture also exposed an existing synchronous fallback bug: after
a DRDY timeout, the scan still read and marked the timed-out slot valid. The
failed slot is now removed from that scan's read phase; another ADC can finish.
This is necessary to avoid accepting an unready result on the affected path.

## Diagnostics and validation

The existing `configUs` measurement now includes configuration **and conversion
start**. `startUs` remains in the diagnostics layout but records no separate
operation (count zero). Compare old `configUs + startUs` with new `configUs` for
the combined setup cost, using totals/counts from matching workloads. Existing
acquisition, ready-wait, row-fresh/reused/no-sample and row-age statistics remain.
The current compact-binary (BDQ v1) final summary serializes these ADC statistics.
The separate multistream (BDQ v2) summary does not: use compact binary for this
ADC-only comparison. A v2 file can establish logger-row delivery but cannot
establish per-ADC setup cost or freshness from its saved footer.

`firmware/tools/test_adc_setup_runtime.py` compiles the full production manager
with only includes replaced, against a command/register/DRDY model. It checks
both ESP32 worker and synchronous paths, with models that do and do not start on
WREG alone. The latter catches the r1 failure instead of baking its assumption
into the fake device. Checks include explicit START after the complete WREG
payload, full restore after a silent ADC reset,
all mux channels, rate/gain/reference changes, independent ADCs, transfer failure,
timeout rejection, recording restart, per-row reuse and completion during setup.
The firmware host Makefile runs it. A saved r1 source can be supplied with
`--manager-source` to prove removal of START fails the START-required model.

Host tests establish command order and software acceptance, not electrical
settling or achieved rate. Target compilation establishes integration only.

## Smallest physical check

Use the A8 ADC-only logger environment, `bodaqs_s3_mini_n4r2`, with CAN master mode
off and remote IMUs/unrelated sensors disabled. Select **BODAQS compact binary**
and **RAW** analog output. LINEAR output with zero configured full travel emits
zero regardless of ADC input, so it cannot expose useful bench signal values.
Begin with one active channel on each ADC at requested 500 Hz. Record effective
rate and configured SPS, setup and
loop costs, wait timeouts, acquisition failures, and per-channel row freshness,
reuse, absence and age. Equal numeric values are not evidence of repeated
conversions; use acquisition/freshness counters.
Keep these format/output settings identical for the baseline and optimized
images. For any later v2 test, ensure unique generated primary field IDs: two
channels with the same `end`, `primary_domain` and `primary_quantity` collide
even if their sensor names differ. Leaving `end` blank derives distinct IDs
from distinct sensor names without inventing a physical placement.

Then select two different, known-safe analog input levels on two channels of one
ADC and scan them at an already supported rate. Check channel association and
settling against an ADC-only baseline, including the first conversion after a
switch, and confirm the other ADC still operates. The old separate START added
uncontrolled wall time after mux selection; combining it into the WREG
transaction shortens that interval.
The datasheet's single-cycle digital-filter settling assumes the analog input
has settled. Board/source impedance and input filtering still require the bench
check. Do not increase admitted rates based solely on command-count savings.

Stop, restart and change rate/channel selection while stopped. Confirm no old
readings are relabelled as fresh. No wiring change, device access, forced storage
stall or mixed-IMU admission is part of this software implementation. An explicit
mixed candidate and its validation follow the ADC-only check.
