# BODAQS

Shared language for the logger, sensor nodes and recorded sensor data.

## Language

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
