# Compact IMU transport with separate timing evidence

On 4 November 2026, the acquisition interview selected compact CAN sample
packets and reception forwarding over SPI, with expansion into native BDQ
records in the logger and separate per-node timing-evidence streams. Repeating
the stored per-sample prefix on SPI consumes too much of the bus shared with
local ADCs; retaining selected raw clock observations separately preserves
auditability without transporting every capture. Timing quality determines
which analyses are suitable rather than excluding otherwise valid sensors;
unknown alignment remains explicit and is never presented as meeting the
unverified 10 us target. The accepted requirements, budgets, persistence order
and qualification gates are in the
[acquisition contract](../firmware/CAN-FD_Acquisition_Transport_Contract.md) and
[network interview record](../firmware/CAN-FD_Network_Protocol.md).
