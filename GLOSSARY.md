# BODAQS

Shared language for the logger, sensor nodes and recorded sensor data.

## Language

**Six-axis IMU sample**:
An associated set of three acceleration and three angular-rate values.
Association does not by itself imply simultaneous physical measurement.

**Native sample timing**:
The placement and spacing of a sensor's samples in its own time reference.
It does not by itself establish their alignment with another sensor.

**Cross-sensor alignment**:
The temporal relationship between samples from different sensors, including the
uncertainty in that relationship.

**Timing observation**:
A recorded clock or acquisition observation used as evidence for reconstructing
sample timing or cross-sensor alignment.

**Sample gap**:
An interval of missing readings within a sensor stream. Its extent may be known
exactly or explicitly uncertain.

**Sample identity**:
The association of a reading with its source, acquisition instance and position
in that source's sequence.

**Unverified sample block**:
A retained group of readings whose required integrity or interpretation checks
have not yet completed. It must not be presented as verified readings.

**Verified reading**:
A reading whose required identity, integrity and sample-association checks have
passed. Verification alone establishes neither timing quality nor durable storage.

**Fresh analog reading**:
An analog reading from a conversion not previously used for that channel's logged
rows. Equal numeric values can come from different conversions.

**SPI measurement profile**:
The operating configuration agreed for the logger-to-CAN-master SPI link over a
recording. Its qualification applies to a specified board and workload combination.

**Source continuity segment**:
An interval of a sensor stream with a common source-sequence origin. Starting
another segment does not by itself mean that the source clock reset.

**Desired configuration**:
The sensor settings saved by the user and owned by the logger.

**Effective configuration**:
The settings accepted and actually applied by a sensor's local driver or remote
node. Adjustments made when accepting a request are limited to explicitly
permitted alternatives.

**Configuration-effective state**:
The state in which an endpoint has a verified applied configuration, whether or
not acquisition is active.

**Acquisition-active state**:
The state in which an endpoint is acquiring samples under its effective
configuration.

**Acquisition lease**:
A renewable, time-limited logger authorization for a node's participating
endpoints to acquire samples.

**Recording membership**:
A node's participation in a particular recording, which can remain in effect
after its acquisition stops and continues to prohibit configuration changes.
