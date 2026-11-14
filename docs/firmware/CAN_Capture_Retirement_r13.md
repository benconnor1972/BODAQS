# r13 CAN capture and retired diagnostic progress

Keep r12 geometry512,16MHz,1200us spacing,5us setup,25us guard, all node images,
ingress128/node, priorities, stacks and no IRQ. Manual installation only.

Selected512-byte master capture capacity becomes32 in BANK1; all older profiles
retain8. Foreground CAN service budget remains8 independently of queue capacity.
This buffers bursts, not persistent overload. No metadata essentialness or CRC,
identity, sample ACK, source admission or physical fence rules are relaxed.

A validated node-addressed management loss report may retire after its local
file gate closes AND its callback retires (gate1, never3). Count omitted diagnostic
messages in the footer separately from sample losses and shared timing omissions;
replays are messages, not unique loss events. An active source retains the normal
loss-record path. Raw sample/evidence objects are never accepted by this rule.
Counters saturate, reset per configuration, and publish only after owner retirement.

Validate real coordinator lifecycle ownership interleavings and raw ISR adapter
capture/service with32 queued receptions and an8-reception service budget. Use
actual master/control/storage/BDQ compositions for repeated post-failure reports,
healthy data, footer counters and normal STOP. Preserve old-profile regressions.
Build both selected targets, review boundaries in fresh Standards/Spec contexts,
run whole host suite and seal source/artifact hashes before manual installation.

Physical run: fresh restart all boards; four IMUs, ADCs off, about60s, normal STOP.
Require actual four-source data, retain serial/config/BDQ and both master structs.
Inspect runtime CAN RX high-water/capacity/drop deltas, stage5 fatal reports,
per-source last sample times and footer diagnostic retirement counts. The master
drain snapshot freezes at first loss, so later fatal events may not be captured.
Exact dropped packet classification is not added in this minimal round; remaining
stage5 faults require targeted per-node master loss-state capture.
