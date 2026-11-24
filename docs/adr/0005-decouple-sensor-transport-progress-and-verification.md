# Decouple sensor transport progress and verification

On 13 November 2026, after real four-IMU overload measurements and a bounded
batching replay failed to establish a worthwhile isolated improvement, the user
accepted a new protocol direction: bounded windows of immutable data, independent
sample/timing/control progress, and sensor-oriented blocks rather than mandatory
preservation of every CAN reception wrapper. This reopens the single selected
batch choice in ADRs 0002/0004, subject to a demonstrated service benefit and an
explicit memory budget; exact window sizes and wire layouts remain undecided.

Normal sample units should fit one physical transfer and be independently
identifiable and checkable, avoiding fragment reassembly on the main sample path.
Use bounded selective recovery so one missing unit does not stop healthy sources;
abandonment must be explicit and counted as loss. Reserve essential control memory
and service independently of ordinary sample capacity. These choices trade some
packing freedom for simpler ownership, bounded repair and continued control under
overload; larger configuration messages may still span transfers.

Preserve unambiguous source/session ownership, strong accidental-corruption
detection and safe acknowledgment, while permitting compact identity encoding
and changes to checksum placement/layers with explicit tested coverage. Checks
not required for safe live operation may occur offline, accepting loss of the
retransmission opportunity and counting later-rejected readings against the loss
budget. Stored unverified blocks must remain distinguishable from verified data;
RAM custody is not SD durability. CRC, length, identity and acknowledgment safety
checks remain live before RAM acceptance. Full stream definitions may be bound
once and referenced compactly, provided source/acquisition/sequence ownership and
restart/wrap safety remain unambiguous. No checksum layer is yet removed.
Retain a master-origin checksum of immutable sample-unit identity/content through
recording and verify it offline, alongside live transfer CRC and storage checks.
This preserves detection across intermediate buffering/copying without putting
all interpretation work in the live path; checksum generation, bytes and evidence
preservation must be budgeted. Healthy qualification requires useful native timing
as well as delivery; degraded timing stays explicit and cross-IMU phase accuracy
remains a separate qualification.

Shed diagnostics and optional timing/alignment detail before readings; preserve
essential interpretation dependencies and protected STOP/authorization service.
Under unavoidable overflow preserve queued history, drop new complete units and
record gaps. Preserve existing recording readability; materially useful new
recording representations require explicit versions and analysis support. Require
a compatible new master/logger firmware pair initially and report mismatches;
automatic fallback to the old wire protocol is out of scope. This retains the
existing logger hardware target and existing CAN node support.

The user confirmed shared understanding after Q1-Q27 and requested specification
on13November2026. The [closed interview](../firmware/CAN_Master_Protocol_Redesign_Interview.md)
retains the decisions, and the [specification](../specs/can-master-logger-protocol-redesign.md)
synthesizes their implementation/testing boundaries. Exact layouts and resource
feasibility require engineering evidence; neither confirmation nor this record
claims demonstrated hardware capacity or authorizes device flashing.
