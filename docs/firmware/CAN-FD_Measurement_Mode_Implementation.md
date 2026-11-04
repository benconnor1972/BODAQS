# Measurement SPI mode implementation (#166)

Implemented on 4 November 2026 against design baseline `8e0c673`, control
baseline `0139d69`, and [specification #164](https://github.com/benconnor1972/BODAQS/issues/164).
The binding layouts and requirements remain in
[the acquisition contract](CAN-FD_Acquisition_Transport_Contract.md), sections
2.2 and 3.2. This record reports software evidence only.

The production master advertises measurement capability bit 3. Shared explicit
little-endian codecs implement the 64-byte BM slot and 64-byte negotiation
payload; both legacy endpoint decoders validate the new reserved fields.
`bodaqs_master_service_process_transfer` dispatches actual CS-bounded lengths,
including active-mode legacy MODE_INFO. Entry binds full boot/session/recording/
context and exact version/1024-byte logical capacity/64-byte physical length/
8 MHz/25 us limits. Matching confirmation is required before the logger reports
`measurementReady()`. Idempotent transition retries retain their original
one-second deadline; timed-out identity remains unavailable. Read-only STATUS
and MODE_INFO use fresh tokens/nonces and cannot establish acquisition permission.

The production master observes CS rising through GPIOA as well as a main-loop
fallback. Retirement reads RX DMA remaining count, drains residual RX bytes,
rejects partial/oversized transfers, resets the SPI FIFO to remove prefetched
TX bytes, and rearms the 84-byte physical capacity. The capacity permits either
64-byte measurement input or 84-byte observational legacy input. CS retirement
only captures bounded input and publishes completed output; protocol parsing,
mode ownership, and control dispatch stay in the main loop. A response is
pipelined and may require multiple fetches. Malformed input preserves context.

The logger uses a bulk shared-SPI transfer at 8 MHz and waits at least 25 us
between measurement slots after the shared mutex has been released. Existing
legacy polling keeps its original guard and settings. Active or ambiguous
measurement mode suspends background legacy polling. Diagnostics under
`can_fd_master.measurement` distinguish observational validity, actual phase,
reason, bound identities, confirmation, unavailable state and selected limits.
64-bit identities are decimal strings. Observing a foreign binding revokes a
previous local confirmation; read-only inspection cannot restore it.

Integration seams for subsequent tickets:

- Logger `enterMeasurementMode(recording, context)`, `exitMeasurementMode()`,
  `measurementReady()`, `inspectMeasurementMode()` and
  `exchangeMeasurementSlot(request, response)`.
- Master `BodaqsMasterService.measurement`,
  `bodaqs_master_service_process_transfer(...)`, and
  `bodaqs_master_service_measurement_fence(stopped_authorization_invalid,
  data_retired)`. Initial fence predicates are true because no acquisition
  producer exists at boot; the acquisition lifecycle must maintain them.
- Fragment transport extends the actual 64-byte service branch. Readiness here
  means confirmed transport only; driver/storage/acquisition qualification gates
  still apply. Configuration-only recording remains unchanged.

Validation passed:

- Common host suite (`gmake -C firmware/can-fd/common/test test`), including new
  independent literal BM bytes/CRC vector (`0x25d45f44`, checked independently
  with Python zlib), malformed lengths/CRC, 84-to-64-to-84 transitions, full
  stale-boot/context checks, exact limits, exit fences, repeated confirmation,
  and non-extending entry and exit deadlines.
- `firmware/tools/test_measurement_runtime.py`: production logger manager and
  master service across pipelined physical SPI, confirmed entry/exit, read-only
  discovery/status, stopped background legacy polls, lost confirmation while
  the master is active, and inspection that never grants acquisition.
- Existing production manager recording-handoff, recovery and runtime-mute
  suites (`test_control_recording_runtime.py`, `test_control_recovery_runtime.py`,
  `test_remote_mute_runtime.py`).
- Explicit MSPM0G3518 master TI build: SDK 2.11.00.07 / TI Arm Clang 5.1.1;
  FLASH 23,256 bytes, SRAM bank 0 5,392 bytes including reserved stack.
- Explicit A8 `pio run -d firmware -e bodaqs_s3_mini_n4r2` build. Resource
  sizes remain build evidence and do not establish runtime memory qualification.

No board was flashed. GPIO/peripheral CS observation, FIFO reset/rearm,
partial-bit transfers, minimum 25 us inactive CS, rearm within 25 us, mutex
ownership at most 100 us, electrical reliability at 8 MHz, and sustained
scheduling occupancy still need #175/#176 physical qualification. In particular,
this host harness supplies CS-bounded bytes; it does not emulate MSPM0 GPIO/DMA
register timing. The active-mode restricted administrative cleanup route and
acquisition grants are completed by the later lifecycle/recovery tickets, with
no legacy acquisition grant enabled by this slice. FIFO/DRDY association,
SYNC/clock quality, four-node load and stack watermarks are not qualified here.
