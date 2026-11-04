# Explicit migration of legacy remote IMU assignments

A saved `bmi270_imu_i2c` entry assigned to `can:N` (or `canN`) remains
readable and unresolved. Loading or inspecting it does not rewrite the saved
file or translate its BMI profile. It cannot participate in recording. Local
BMI270 assignments retain their existing profile meanings and driver behavior.

While idle, open the sensor editor, choose the migration type
`lsm6dso32x_imu` and profile `imu6_3333_32g_2000dps_v1`, then select
**Migrate saved assignment**. The ordinary type selector directs legacy-to-LSM
changes to this action so defaults cannot silently select a profile. Migration saves those selections only; save any
other form edits separately. The API exposes the same action in each legacy
sensor's `migration` object. Submit to `PUT /api/v1/sensor?id=N`:

```json
{"migration":{"type":"lsm6dso32x_imu","profile":"imu6_3333_32g_2000dps_v1"}}
```

Name, mute default, provider/endpoint, calibration and mounting metadata stay
with the assignment. Retained legacy acquisition keys are opaque and do not
configure the LSM device. The chosen canonical LSM profile maps to wire profile
1/version 1, using the same asynchronous reconciliation as a new LSM assignment.
Invalid selections, incompatible retained metadata, recording lock and failed
persistence preserve the previous saved entry. Correct incompatible metadata
explicitly before retrying migration.

A successful save reports saved desired configuration separately from pending,
rejected or unknown node application. This configuration-only stage does not
provide sample acquisition or recording readiness. See the
[node control contract](CAN-FD_Node_Control_Contract.md), section 10.

Host fixtures cover unchanged legacy reload/readback, API and web migration,
metadata/calibration retention, invalid selections/mounting, save failure,
recording lock and rejection of migration for local BMI assignments. The A8
build checks target integration. Actual browser interaction, SD failure and
node register readback still require device verification; no upload is implied.
