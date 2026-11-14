# r11: bulk transport with 1,200 us minimum start spacing

This logger-only diagnostic follows the r10 physical result. Keep the exact r10
master image, CAN node images, four-IMU/ADC-off configuration, wiring and SD card.
Use `bodaqs_s3_mini_n4r2_imu_bulk_pace1200`; installation is manual.

The only functional change from the r10 logger is minimum per-CS start spacing:
600 -> 1200 us. The new environment removes the inherited 600 us definition
using `build_unflags` and adds 1200. Audit resolved compiler definitions so it
does not accidentally fall back to zero spacing. The r10 environment is preserved.
Version 5, 512-byte physical transfers, 128 meaningful command bytes, 16 MHz,
5 us CS setup, 25 us rearm guard, CRC/identity/custody policy, four immutable
sample slots, diagnostic flags, priorities, task stacks and all queues retain
their r10 settings. Master ingress stays 128 receptions/node. No IRQ is added.

The master requires a minimum rearm guard, not an exact 600 us logger cadence;
no mode negotiation field or master firmware change is needed. Per-CS spacing
continues to release the shared SPI mutex while waiting.

## Question and comparison

r10 measured about 828 us mean outer request-processing time in its first-loss
snapshot, including interrupt time, versus 472 us in r9. Its 600 us minimum
spacing allowed request drops and reply-publication delays. This experiment
tests whether wider spacing reduces that churn and preserves control/evidence
progress. It does not establish that slower polling raises the capacity ceiling.

Start with fresh board restarts and configuration reconciliation. Record about
60 seconds with four IMUs, ADCs off and primary 500 Hz, then request normal STOP.
Save finalized BDQ, full serial, unchanged config export and post-cleanup master
counters before another start. Preserve a failed attempt; source exclusion is
evidence, not a reason to discard it. No artificial storage stall is requested.

Compare source-bounded delivery and sustained progress, metadata/STOP survival,
SPI receive drops, reply rejections, proof latency, ingress and sink pressure.
The drain snapshot freezes at first loss or normal STOP; do not treat its phase
means as a full-run average. Boot runtime totals have a different scope. Prefer
the existing binary snapshot helper to avoid rounded 64-bit context identities.

If receive drops and proof latency improve but useful delivery stays limited,
optimize measured master work next. If early malformed replies persist despite
lower pressure, capture their bytes/extents before attributing them to hardware.
The node-exclusion/shared-metadata lifecycle concern remains open; this round
does not claim to fix it or expand admission.

## Validation scope

Reuse the complete host validation at r10 source
`92dfbce2b63708a6ea18514249d420ecd45d89dd`: production source is unchanged.
Run existing public pacing/CS-setup checks and manager pacing propagation at
1200 us, build the selected logger, compare normalized recipe inputs/options,
audit effective compiler definitions and memory, and verify package hashes.
Keep the exact r10 master and pinned decoder, with a new logger recipe identity.
Physical timing, capacity and runtime watermarks remain unqualified.
