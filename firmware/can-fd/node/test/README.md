# Node acquisition hardware-boundary fixtures

Run `gmake test` here with GCC on PATH. The fixtures compile the production
`imu_spi.c`, `imu_capture.c` and `imu_acquisition.c` against a narrow TI
register/driverlib boundary. They do not replace acquisition with a state model.

- `test_spi`: literal command F8; 673 RX/TX bytes for 96 tagged words; RX-before-TX;
  command-phase junk exclusion; CS held until RX count reaches zero and SPI idle;
  timeout/cancel disables both channels; stale IRQ cannot finish another block.
- `test_capture`: literal CC2/ZERO inputs in both edge orders, native epoch retained;
  trigger overflow is a fault rather than a rollover; bounded ring exhaustion;
  a service blackout spanning possible multiple wraps is untrusted.
- `test_acquisition`: literal gyro/acceleration/timestamp words and signed axes
  (-32768, 32767, -1), modulo-four slot counters and a synthetic raw sensor-tick
  wrap; actual GPIO-CS/register/DMA and ISR capture ingress; observed 70 ms plus
  270 gyro/10 acceleration discards on cold and warm preparations; no pre-roll;
  source sequence zero at the first subsequent acceleration-ready slot; model,
  anchor and snapshot before data under 6 ms CAN backpressure; FIFO/timestamp off
  at STOP with enabled engine registers preserved; hardware-TX quiescence before
  FENCE; duplicate/unexpected engine tags, timestamp skips, missing captures and
  post-drain overruns fail without an ambiguous six-axis output.

Set `BODAQS_NODE_FIXTURE_OUT` to an absolute output filename to retain actual
production CAN frames as `decimal_identifier decimal_length hex_payload` lines.
This enables independent master/logger/BDQ integration checks. Node identity is
boot 17/address 0. Model slopes come from 32 observed capture intervals, not the
nominal ODR. Native association is explicitly seeded by a no-edge FIFO-enable
fence, then checked against FIFO slot progression, sensor timestamps, capture
ordinals and observed cadence. Any seed transition edge causes bounded restart;
ambiguous ongoing association excludes safely. Uncertainty remains unknown.

Production pins: G3507 RHB32 PA3/TIMA0_C2 acceleration DRDY, PA22/TIMA0_C1
watermark, PA25/TIMA0_C3 SYNC input; SPI0 mode 3, 4 MHz, DMA channels 0/1.
The nominal 1 MHz 16-bit timer is extended with ZERO interrupts and is never
restarted by PREPARE/START/STOP. Every preparation explicitly resets the sensor
counter with documented TIMESTAMP2=AA, verifies a small raw counter afterward,
and advances its distinct clock epoch. Clock-reset evidence carries that
observation tick, not an asserted exact electrical reset edge. Raw SYNC captures
can be retained without claiming association to an unobserved master sequence.

The baseline CAN 500 kbit/s / 2 Mbit/s profile remains for the one-node ticket;
link profile selection and broader admission are separate work. The 96-word,
5 ms fallback, 10 ms first-free and 1 ms repeat-gap values are implementation
and bench validation targets. These deterministic fixtures and the explicit
G3507 target build do not qualify FIFO/DRDY phase association, sensor/filter
phase, interrupt latency, physical SPI/SYNC timing, 10 us inter-node alignment,
DMA/bus fault recovery or debugger-halt continuity. Perform the deferred board
qualification before asserting those physical properties.
