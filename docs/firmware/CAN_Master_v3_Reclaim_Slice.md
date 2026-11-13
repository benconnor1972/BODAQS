# v3 scheduling carry-over before multi-unit windows

The r4 two-node run fills master ingress within 477,501 us while storage stays
healthy. It loses 21.9573% on node 0 and lacks node 1's final boundary, with 470
unresolved readings. This provides the reference for the next scheduling slice.

The opt-in `bodaqs_s3_mini_n4r2_imu_units_reclaim` environment extends the r4
two-node, ADC-off, storage-priority-2 build with
`BODAQS_RECLAIM_IDLE_CONTROL_FETCH=1`. The existing v2 idle-control reclamation
implementation is permitted on v3. It preserves urgent exchanges, real pending
ordinary/protected results, acknowledgments, known partial objects and blocked
RAM heads. Otherwise it uses the existing round-robin data selector. V3 sample
fetches retain their existing translation to opportunistic IDLE/sample delivery.
No new ACK semantics, memory window, credits, physical buffer ownership or master
firmware change is introduced. Old environments/defaults remain unchanged.

The two-node integrated test first failed on the v2-only compile guard. With
the port it passes independent source values/sequences, both partial STOP
boundaries, lost ACK, cancellation, short write and stale authorization/restart.
The existing v2 selector's pending/control/ACK/fairness tests remain applicable;
hardware clocks/SPI/storage in these host fixtures are substituted. No host timing
is promoted to physical progress or a bound on control latency.

The node-1 stream failure cannot be reproduced exactly from the recording: the
failing wire observation was not retained. Rather than guess which validation
failed or relax it, RemoteImuStream retains the first failing source line. It is
atomic, reset at configuration, and exposed in the existing remote failure footer
as optional `stream_failure_site`. Map it to RemoteImuStream.cpp in the exact
SOURCE.zip/recipe; it is a diagnostic source location, not a stable wire reason.
All existing fail-closed checks remain active. Essential-queue exhaustion coverage
checks that a first site exists and cannot be overwritten by a later failure.
The site covers latched `stream.failed()` (the observed cause 3), not every
`Invalid` return: non-latching rejected inputs can still yield a local fault with
site zero. Reconfiguration clears the diagnostic after the old owners retire.

Retest the same two-node load, card and config for approximately 60 seconds.
Compare source-bounded delivery, per-node fairness, duplicate/empty work, ingress
loss, storage pressure and source STOP evidence. The footer should now localize
any repeated stream failure. Current node-1 reported management-loss totals are
anomalous and must not be promoted to unique-reading loss; preserve them for the
next diagnosis. A missing final bound remains an incomplete result.

This is a bounded first scheduling investigation under the approved redesign,
not completion of T03 multi-unit windows or T04 control/evidence isolation.
Those tickets' window/credit/repair/retirement acceptance criteria remain open.
Do not claim that this port fixes the observed evidence accounting or STOP fault,
or that it will supply enough two/four-node throughput. No additional node or
master flash is required; node flashing remains user-managed as agreed.
