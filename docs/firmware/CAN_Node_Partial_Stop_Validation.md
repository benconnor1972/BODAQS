# Node partial STOP packet correction

The first physical v3 one-IMU recording retained 8,119 sample units but rejected
unit 8,120 at STOP with fragment error 13. The node set reserved compact-packet
bit 7 when flushing a nonempty final packet. Both the compact observation and
v3 sample-unit contracts require bit 7 clear. The source STOP boundary already
provides the terminal sequence; the packet itself needs no additional flag.

The correction removes the private `flush` function's final/nonfinal distinction.
It preserves packet counts, first/gap flags, zero padding, CRC checks, raw axes,
identity checks and the independent source boundary. No public API, configuration
field or wire layout changes. Existing logger/master images remain compatible.

## Regression

`firmware/tools/test_sample_unit_recording_runtime.py` now runs both the original
65-reading trace and a 64-reading trace. The latter exercises the real node's
partial STOP packet through the production master service, logger RAM custody,
BDQ writer and independent Python decoder. It requires all sequences 0–63,
no gaps or ambiguous packets, and a retained source STOP boundary identifying
63 as the last sequence. Only hardware/timer boundaries are substituted.

Before the correction, the new trace failed in production fragment acceptance
with the same error as the device. After the correction it passes, including
the existing checksum-corruption and foreign-epoch negative cases.

The acquisition-profile MSPM0G3507 target compiles with warnings as errors.
Independent Standards and Spec/boundary reviews against base
`aaca23a51616921c067e1d690e790a4275f11995` reported no findings. The Standards
reviewer independently reran the runtime regression successfully. Broader host
results and exact installed-image verification belong in the r2 kit manifest;
their completion is not inferred from the focused regression or target build.

## Physical follow-up

Flash only selected node 0, acquisition CAN profile, after matching its hardware
UID and preserving its existing FLASH. Keep the exact prior v3 logger/master
images and one-IMU, ADC-off configuration. Repeat approximately 30 seconds and
normal STOP, saving finalized BDQ, serial, actual config and stopped-master
diagnostics in a new result folder. Confirm the terminal boundary and assess
loss; early ingress overflow was independent of the STOP mismatch and may remain.
This correction alone is not a throughput qualification or a pipeline redesign.
