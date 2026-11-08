# Combined ACK/fetch probe - round17

Bench experiment only. The user accepted redirecting effort from CS-high gap
publication to useful throughput on 9 November 2026. This round implements the
existing protocol1 ACK_FETCH primitive in the logger; it does not qualify native
CAN/IMU, SD persistence, electrical timing or production admission.

## Controlled comparison

One logger binary exposes existing `owner_flow` and new `owner_fetch` modes.
Both use the same owner-row scheduler, four pending requests, CLOCK bypass,
1008-byte immutable objects, full frame/object/known-byte validation, ADC workload,
500us start pacing, 25us guard, 800us row reserve and bounded retries. Existing
commands retain their behavior. The added mode accepts the same arguments as
owner_flow, including optional trace0/1. Results/build identities advance to v17;
wire version remains1. No recording or analysis data format changes.

Use the same new boundary-only master for both modes: acquisition CAN profile,
queue4, table CRC, trace enabled, ownership flag0 and gap flag0. The only master
source change includes ACK_FETCH preparations in the existing trace filter. No
SPI, DMA, CS, publication, clock or ADC configuration change is made. Trace-off
still retains the existing observer code/arena; this is a matched binary comparison,
not a claim that observation is compiled out.

One bounded original round14 logger/late-master run provides a historical pair
reference. Use exact sealed copies, never a rebuild. It is separate from the
same-binary flow/fetch comparison. Do not extend this into another timing sweep.

## Confirmation and lifetime

Each pending entry stores its actual opcode and the old immutable object ID.
Only fully validated RAM acceptance permits ACK_FETCH. A fragment0 response with
the next object ID can confirm the old retirement only while the matching
ACK_FETCH is pending for that node. Validate new identity, expected logical CRC,
exact length and every known byte before clearing pending, incrementing confirmed
retirement and seeding the next object. Full new-object CRC remains mandatory
before its later ACK. A response proving master action is not SD persistence.

Repeated combined replies for the current object are duplicate fragment0 data;
they do not clear another request or retire again. Older/future contexts remain
stale. An ordinary ACK cannot confirm an opcode4 pending request. Retries reuse
the old object ID and its CRC, retain their original age, and stop after eight
retries despite other nodes progressing. At UINT32_MAX use ordinary ACK and
terminate after its confirmation, without fetching object0. BEGIN/STOP and case
ID fencing remain unchanged. Failed STOP blocks reuse as before.

## Evidence and interpretation

Host tests drive actual logger, codec and master engine with simulated delayed
full-duplex replies. Loss/corruption tests include applied ACK with lost reply,
duplicate delivery, wrong next object/case, CRC/length/payload/fragment changes,
ordinary ACK substitution and one node exhausting retries while peers progress.
An explicit test-only initial-identity seam seeds both endpoints at max-1; target
initialization remains object1. Production adapter tests include opcode4 in the
bounded trace's publication/retirement/STOP lifecycle. Hardware FIFO/shift timing
is not modeled. A fresh boundary review is required before sealing the bundle.

Analyzer v17 recognizes the new mode and both logger/master opcode4 trace forms.
All earlier result schemas retain their interpretation; compare historical
reports for byte-equivalent parsed results. No analyzer pass waives CAN/SPI loss.

Count useful throughput as ACK-confirmed objects*1008/elapsed seconds. RAM accepted
bytes are separate. ACK_FETCH retires one object and prepares a fragment in one
request: prepared_fragments+retired_objects double-counts combined operations.
Do not reuse round16's separate-ACK queue accounting for this mode. Pending tails
at timed cutoff are not confirmed useful bytes. Stats endpoints include controls.

Ideal steady-state work falls from six useful requests per object to five at
256 bytes. That is a 20% arithmetic capacity opportunity, not a measured gain.
Judge the candidate against the bracketing same-binary baseline, fresh ADC rows,
wire/retry/loss observations and eventual admitted concurrent workload. About
200 decimal kB/s is a working synthetic threshold, not the required 1.25x margin
or a replacement for shared-SPI85%/CAN70% limits and sustained qualification.

## Bench stop rules

Use manual uploads only; load the master and Run/F8, then reboot/check logger.
Retain complete serial captures and operator image/reset records. No scope capture
or gap variant is needed for this round. Stop/review on wire/transfer/accept errors,
exhaustion, missed/reused/no-sample rows, ADC failure, incomplete STOP or any SPI
queue loss. Background CAN drops remain explicit failures of overall qualification;
the synthetic comparison may be described only with that existing limitation.
No silent loss waiver, frame repair, validation removal or automatic fallback.

See [ADR0002](../adr/0002-drain-capacity-redesign-boundaries.md),
[ADR0004](../adr/0004-reopen-spi-transaction-envelope.md) and the
[SPI revision contract](CAN-FD_SPI_Transaction_Revision.md). The sealed bundle's
runbook contains exact images, identities, commands and fallback instructions.
