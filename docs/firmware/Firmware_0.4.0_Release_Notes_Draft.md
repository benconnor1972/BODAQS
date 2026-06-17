# BODAQS Firmware 0.4.0 Release Notes Draft

Status: draft  
Release date: TBD

Firmware `0.4.0` extends the logger's external sensor support and tightens the
runtime split between logging, upload, and configuration workflows.

## Highlights

- Added UART GPS support for SparkFun DAN-F10N/u-blox modules.
- Added asynchronous sensor caching so lower-rate sensors can feed the
  synchronous log row without blocking the logging loop.
- Added AS5048B and AS5600 rotary angle sensor support over I2C.
- Added rotary angle `direction` calibration while continuing to emit legacy
  `invert` metadata for downstream compatibility.
- Added AS5600 rotary angle support as a practical fallback angle sensor.
- Moved I2C bus speed ownership into board profiles.
- Updated Proto-F and RC3 UART profile mapping to GPIO43 TX and GPIO44 RX.
- Improved upload/config mode ownership so Wi-Fi, GPS, and web routes are not
  unnecessarily kept alive during logging.
- Reduced dynamic web UI pressure by simplifying generated sensor/config pages.

## Compatibility

Existing configs should continue to load. AS5048B and AS5600 angle sensors may
now persist:

```text
sensorN.zero_count=<count>
sensorN.direction=counts_increase_positive
```

or:

```text
sensorN.direction=counts_decrease_positive
```

For rotary angle sensors, `direction` is the firmware-owned polarity field.
Generated metadata still includes `invert` for compatibility with existing
downstream consumers. `invert=true` corresponds to
`counts_decrease_positive`.

## Calibration

The on-device `ZERO` calibration for rotary angle sensors is now two-step:

1. Capture the installed zero position.
2. Move the measured linkage in the intended positive direction and capture
   the second point.

The second capture is used only to determine polarity. It does not create a
full-range calibration; rotary angle output remains based on the sensor's native
counts-per-revolution scale.

## GPS Logging

GPS data is sampled asynchronously and cached. Log rows use the most recent
valid GPS sample according to the sensor's emission policy, with validity and
semantic details recorded in metadata for downstream preprocessing.

## Known Notes

- Rotary angle sensors are single-turn sensors in this release.
- Compact binary logging is still being hardened alongside the new asynchronous
  sensor model.
