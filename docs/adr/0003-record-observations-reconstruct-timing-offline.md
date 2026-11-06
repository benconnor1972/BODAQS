# Record observations and reconstruct IMU timing offline

On 6 November 2026, the drain-capacity redesign selected separate preservation of
compact IMU readings and timing observations, with per-sample timing reconstructed
by analysis tools. The current logger expands readings only when an applicable
timing model is available; this couples retention of otherwise interpretable
readings to timing-evidence availability. Moving reconstruction offline accepts
updated import/analysis tooling and a new, explicitly versioned representation
in exchange for a simpler recording path and honest retention of untimed data.

This revises the logger-expansion choice in
[ADR 0001](0001-compact-imu-transport-and-separate-timing-evidence.md), retaining
compact transport and separate timing evidence. Existing recordings remain
readable. Source identity, configuration, integrity and sample association remain
essential; unavailable timing must stay explicit. The current sample schema
cannot silently be reused for absent sample timestamps. Exact representation,
evidence policy and analysis behavior remain design questions.

The user subsequently agreed that timing observations may be persisted after
related readings and resolved across the file by analysis. Interrupted recordings
may retain untimed readings, provided essential identity and interpretation
information survives. Analysis exposes those readings by sample sequence and
reports affected intervals; operations requiring unavailable timing exclude
them explicitly. Nominal-rate approximation, if added, requires explicit
selection and an estimate label. Healthy acquisition should normally provide
continuous reconstructable native timing from observations; untimed retention
is an exceptional fallback. Evidence cadence requires reconstruction-quality
measurements rather than inheriting the current model refresh interval.

The selected representation direction is a dedicated versioned packet-observation
schema in the existing BDQ container, preserving existing sensor schemas. Packet
observation timestamps describe observation, not sensor acquisition. Exact byte
layout and schema identifier remain implementation/specification work.

The node retains internal checks for correct sample association but exports raw
timing observations relating full sample sequence and sensor/node clock readings,
at recording boundaries and periodically. Offline analysis fits timing between
these observations instead of treating repeated short-lived firmware models as
authoritative. Sparse observations do not recover each sample's actual acquisition
time; inferred timing stays labelled and unsupported intervals stay unknown.
Cadence is selected against reconstruction quality and a bounded traffic budget.

This is an accepted design direction, not an implemented or qualified format.
SPI already carries compact readings, so this decision does not itself reduce
SPI wire traffic or establish adequate drain capacity. The broader boundaries
are recorded in [ADR 0002](0002-drain-capacity-redesign-boundaries.md).
