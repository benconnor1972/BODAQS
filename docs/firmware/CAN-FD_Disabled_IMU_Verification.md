# Disabled IMU configuration verification (#158)

This procedure is repeatable bench work, **not recorded physical evidence**.
Host simulations and target compilation do not establish electrical timing,
register truth, stack high-water or sensor power consumption. No device upload
was performed for this change. Acquisition and enabled profiles remain unavailable.

Use the production MSPM0G3507 RHB32 IMU-only node with LSM6DSO32XTR, the
MSPM0G3518 master, and A8 logger (`bodaqs_s3_mini_n4r2`). Record board revisions,
firmware commit IDs, SDK/compiler versions, supply voltage, instrument model,
trace filenames, observed values and pass/fail against each limit below.

## Automated evidence

Run `make -C firmware/can-fd/common/test test` with a host C++ compiler. The
disabled fixture uses independent literal metadata/register-image bytes,
controlled registers and time, real SPI slot/CAN codecs and master exchange,
the existing authority owner, staged apply and immutable snapshot service. It
covers dropped COMMIT response, exact replay, fresh no-op verification, first
revision 1, accepted generation/session, expiry without incoming traffic,
conflicting/incomplete staging, abort retry, stale scope/revision and faults
14–18. Register simulation does not model electrical behavior.

After installing the A8 dependencies, run
`python firmware/tools/test_control_apply_runtime.py` and
`python firmware/tools/test_control_authority_api.py`. These exercise production
desired selection/agreement/JSON using real ArduinoJson. Active legacy remote
BMI270 ownership remains unresolved; unassigned or muted ownership can request
disable without rewriting saved configuration.

Build both TI targets with the pinned SDK 2.11.00.07 / TI ArmClang 5.1.1.LTS
and SysConfig 1.28.1 using their `ticlang/makefile`, and build A8 with
`pio run -d firmware -e bodaqs_s3_mini_n4r2`. Inspect the node map: mutation
staging (512 bytes), snapshot storage and effective observations are static;
the 2048-byte stack reservation is not a measured stack bound.

## Board procedure

1. Connect logic-analyzer probes to PA8 CS, PA9 PICO, PA10 POCI and PA11 SCK,
   plus PA3 INT1 and PA22 INT2. Confirm safe voltage levels for the exact board.
   Power-cycle the node. CS must be high before GPIO output enable, clock mode
   must be mode 3 and nominal SCK 1 MHz; CS must span both command/data bytes.
   INT pins remain inputs without driven-high pulls or acquisition IRQ handlers.
2. Leave the logger idle with the endpoint unassigned, or assign the remote
   endpoint and mute it. Capture saved settings before/after. Discover, inspect
   descriptors and bind a fresh session. Config/readback features must be set,
   supported enabled-profile count zero and acquisition readiness false. BEGIN
   has a client-allocated nonzero transfer ID, schema 1/v1, length 44, desired
   generation and expected revision. Page lengths are exactly 24 and 20; the
   same immutable 24-byte metadata appears in COMMIT.
3. Pause after BEGIN/pages, before COMMIT. There must be no sensor register IO.
   Inspect GET_OPERATION: kind 2, target mutation sequence, request opcode 14h.
   Abort (including lost-ack retry), omit a page, alter an already staged page,
   and let staging expire after 5000 ms on separate operations. Each must end
   without sensor application. Expiry advances without any incoming CAN frame.
   Abort records terminal mutation rejection (reason 9, field record), while
   its command acknowledgement remains retryable; it cannot cancel COMMIT.
4. Submit complete disabled descriptor (`01 00 01 00`, remaining 40 bytes zero)
   and COMMIT. Measure reset completion below 100 ms and full application below
   2000 ms from commit acceptance. During reset, send GET_NODE_STATE,
   GET_OPERATION and snapshot requests; main-loop processing must stay responsive.
   Capture register exchanges and verify WHO_AM_I 6Ch, CTRL1_XL owned bits 04h,
   CTRL2_G 0Ch, CTRL3_C 44h, CTRL4_C 0Ch, CTRL9_XL E2h. Verify owned FIFO,
   batching, counters, interrupt routes and timestamp fields zero. Reserved
   fields are preserved, not bulk-cleared. See the contract and research note
   for masks and the complete image; no sample/FIFO data register is collected.
5. Verify embedded-bank EN_A (04h mask 38h) and EN_B (05h mask 19h) zero;
   sensor-hub MASTER_CONFIG (14h mask 14h) zero, and successful return to user
   bank. These checks extend the owned disable proof to embedded/auxiliary
   enables. The 24-byte wire image is still the contract's user-bank image.
6. Read the eight-page effective snapshot and a fresh endpoint GET_NODE_STATE.
   Epochs must agree. Expect verified-disabled, both engines off, acquisition
   false, revision 1 on first success, matching desired generation and accepting
   session, known/current identity/engine/register-proof groups (mask 441h),
   acquisition-only groups not applicable, and no invented measured rates.
   Logger `configuration_reconciled` becomes true only from this current
   snapshot, health and matching desired/session evidence. Status bit 0 includes
   verified disable; Health reports C:apply while pending, then C:ok.
7. Drop an application result and retry the identical COMMIT with its original
   expected revision. Cached success must return without new register IO/reset.
   Use a **new** operation for the same desired settings: all owned fields must
   be freshly read, with no reset/revision advance on a complete match. Change
   desired generation on another identical operation: acceptance/epoch change,
   revision remains unchanged. Change a documented owned field using a bench
   debugger/instrument and repeat: fresh verification must detect it and take
   reset/apply/readback under the same application deadline.
8. On separate runs inject absent/miswired sensor/SPI timeout (14), wrong
   WHO_AM_I (15), reset bit held beyond 100 ms (16), failed owned-register write
   or readback (17), and a backend stalled beyond 2000 ms (18). Use a documented
   bench fault shim when the physical sensor cannot reproduce a fault safely.
   Expect terminal rejection, current-unknown/fault health, cleared pending,
   and previous proof retained only as historical. Mismatch evidence includes
   address, expected masked value, observed masked value and comparison mask.
   No acquisition readiness is granted. SPI timeout recovery raises CS and
   resets/reinitializes SPI0 to remove queued TX; verify no stale queued command
   reaches the next transaction. Trace any sensor bank left on a failed path;
   a later operation explicitly reselects user bank before interpretation.
9. Check stack watermark, main-loop latency, CAN queue/drop counters, repeated
   operations and idle GPIO/SPI behavior under sustained inspection. Confirm
   no sample messages, no FIFO accumulation from batching, and no configured
   acquisition interrupt routes. Record physical observations separately from
   the automated pass log.

Master restart/reconnect/session renewal is follow-on #161. Enabled desired
profiles and shared configuration editing/reconciliation are follow-on #159.
This slice preserves the transfer allocator within a logger session across a
master information reset; it does not claim recovery from lost authority.
