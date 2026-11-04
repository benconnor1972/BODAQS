# 02: Preserve responsive discovery while deferring transport processing

## What to build

Prepare the master and node to process control work cooperatively outside
interrupts while preserving today's logger probe, status and node discovery
behavior. A user must still see a responsive Health screen and coherent
inventory under transport traffic. Keep this preparation separate from adding
new configuration operations.

## Acceptance criteria

- [ ] Interrupt handlers perform bounded transport work and hand complete records to fixed-capacity processing outside interrupts.
- [ ] Existing SPI bootstrap layouts, chip-select/DMA sequencing, CAN announcements/status and coherent inventory behavior remain compatible.
- [ ] Queues expose capacity/overflow evidence and fail by whole record; there is no unbounded command allocation or interrupt-time hardware configuration.
- [ ] Existing host checks and both production MSPM0 target builds pass; relevant logger bootstrap checks remain green.
- [ ] A repeatable verification procedure demonstrates responsive bootstrap/discovery and documents hardware timing checks still requiring on-device evidence.

## Blocked by

None (can start immediately).

## Publication preview

Repository: benconnor1972/BODAQS. Intended labels: enhancement, ready-for-agent,
when available. No source parent issue was supplied. Preview only; not published.
