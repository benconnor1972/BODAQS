# Bounded two-node v3 recording bench

The priority-2 one-node reference retained 116,623 of 116,633 source-bounded
readings, with no primary drops or unresolved identity and successful STOP.
It does not establish two-node capacity. The next case selects nodes 0 and 1,
leaves ADCs/unrelated sensors off, retains primary rate 500 Hz, and records
approximately 60 seconds on the same card. No return-to-priority-1 check is
required: the user explicitly chose to move on.

## Implementation scope

`bodaqs_s3_mini_n4r2_imu_units_two_node` inherits the priority-2 v3 environment
and adds `BODAQS_V3_TWO_NODE_BENCH=1`. It uses a distinct explicit admission
mode, `sample_unit_two_node_unqualified`, without enabling the legacy mixed-ADC
bench macros or changing production/reference admission. Its bench evaluator
admits exactly one or two nodes, 500 Hz primary, no ADC conversion demand or
active ADC channels, and no unrelated active sensors. Other counts/rates fail
closed. Invalid v3/legacy-bench compile combinations fail during compilation.
Existing eligibility, duplicate-address, link compatibility, RAM allocation,
identity, CRC and control lifecycle checks remain in force.

The additive evaluator/reason are internal firmware interfaces; old reason
numbers are preserved by appending the new reason. API/footer admission mode,
reason text and the web configuration warning describe the new bench correctly.
Record schemas, configuration fields, bus settings, buffers and peer protocol
are unchanged. Both sample streams use the existing per-source v3 custody.

Node 1 needs the same corrected acquisition-profile node image already installed
on node 0 (`462346c9411cbdc4bb7348d3543f3c8168a05450`). That image is common to
node addresses; the user elected to flash all nodes manually. The agent does
not program nodes for this round. The master remains unchanged.

## Validation

Public admission regression exercises allowed counts 1/2, rejected counts 0/3/4,
wrong rates, active ADCs/conversion demand, unrelated sensors and production
fail-closed behavior. The initial test failed because the new evaluator did not
exist; the guarded implementation passes. Legacy admission cases remain intact.

The integrated production manager/coordinator/RAM/BDQ fixture now also runs two
v3 sources. Both carry sequences 0–63 and partial STOP packets, with distinct
literal acceleration values per source so accidental substitution is observable.
It requires both terminal boundaries at sequence 63, no gaps/ambiguity, exercises
lost ACK, short write, cancellation and stale authorization after restart, and
keeps the minimal host footer incomplete rather than claiming physical closure.
Hardware clocks, SPI and storage boundaries are substituted; real throughput and
electrical behavior are not inferred from host timing.

The multi-node assessor now selects v3 sample-unit streams as well as legacy
compact packets, retaining the same per-source CRC, identity and coverage
checks. Before this change, the integrated two-source file failed expected-node
membership; afterward it is recognised. Expected membership 1 or 4 still fails
for the two-source file. Existing legacy multi-node analysis tests pass.
The new integrated case is wired into the host/candidate runner; admission
coverage is wired into the firmware host suite.

Fresh Standards and Spec/boundary reviewers inspected the diff against
`88ed933280715f7833c82d510565f762358bdb48` and reported no findings. The Standards
reviewer independently ran the new admission and two-source integrated suites
successfully. Final broad-host, target-build and installation evidence is retained
in the r4 kit; these reviews do not establish physical acceptance.

## Physical follow-up

Install the reviewed logger image and the provided two-IMU ADC-off configuration.
Require five streams (primary plus two sample/timing pairs), with no excluded
IMU. Preserve both per-node final boundaries, complete serial, actual config,
finalized BDQ and stopped-master diagnostics where available. Compare each node
individually for loss and service fairness; totals alone are insufficient.
Capacity and native timing remain unqualified pending actual measurements.
