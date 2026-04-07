# AS5600 String Pot Over I2C: Context Summary

This note summarizes the relevant parts of the recent work and debugging around adding an `AS5600`-based multi-turn string potentiometer read over I2C to the BODAQS firmware.

It is intended as handoff/context for a future chat.

## High-level outcome

- The firmware now has an `AS5600 String Pot (I2C)` sensor type implemented.
- The shared unwrap/calibration logic is in place and is shared with the analog AS5600 string-pot variant.
- The current blocker for reliable use on the existing hardware is **I2C address conflict** with the onboard fuel gauge:
  - `AS5600` fixed I2C address: `0x36`
  - `MAX17048` fuel gauge fixed I2C address: `0x36`
- As a result, the plain AS5600 cannot coexist on the same bus as the MAX17048 without hardware changes:
  - use a second I2C bus
  - use an I2C mux/switch
  - keep the AS5600 in analog mode
  - or use a different sensor variant/device

## Architecture decisions

### Sensor class model

We decided not to model the AS5600 string pot as just another analog pot.

Instead:

- `Sensor` remains the common interface
- `AS5600StringPotSensorBase` owns:
  - wrapped-to-unwrapped tracking
  - startup assumptions
  - smoothing
  - calibration behavior
  - output column behavior
- Transport-specific subclasses provide only the wrapped reading:
  - `AS5600StringPotAnalog`
  - `AS5600StringPotI2C`

This was important because the AS5600 is a wrapped one-turn sensor whose real position must be reconstructed as multi-turn unwrapped counts.

### Output behavior

The intended behavior is:

- primary output in `RAW` mode: wrapped counts
- primary output in `LINEAR`: unwrapped mm
- optional extra raw column: wrapped counts
- `currentRawCounts()` for the AS5600 family returns **unwrapped calibration-space counts**

That last point was chosen so the existing ZERO/RANGE calibration mechanism could still work.

## Files/classes added or changed

### New / relevant AS5600 files

- [AS5600StringPotSensorBase.h](C:/Users/benco/dev/BODAQS/firmware/src/AS5600StringPotSensorBase.h)
- [AS5600StringPotSensorBase.cpp](C:/Users/benco/dev/BODAQS/firmware/src/AS5600StringPotSensorBase.cpp)
- [AS5600StringPotAnalog.h](C:/Users/benco/dev/BODAQS/firmware/src/AS5600StringPotAnalog.h)
- [AS5600StringPotAnalog.cpp](C:/Users/benco/dev/BODAQS/firmware/src/AS5600StringPotAnalog.cpp)
- [AS5600StringPotI2C.h](C:/Users/benco/dev/BODAQS/firmware/src/AS5600StringPotI2C.h)
- [AS5600StringPotI2C.cpp](C:/Users/benco/dev/BODAQS/firmware/src/AS5600StringPotI2C.cpp)

### Sensor/config plumbing

- [SensorTypes.h](C:/Users/benco/dev/BODAQS/firmware/src/SensorTypes.h)
- [SensorRegistry.cpp](C:/Users/benco/dev/BODAQS/firmware/src/SensorRegistry.cpp)
- [ConfigManager.cpp](C:/Users/benco/dev/BODAQS/firmware/src/ConfigManager.cpp)
- [SensorManager.cpp](C:/Users/benco/dev/BODAQS/firmware/src/SensorManager.cpp)
- [Routes_Config.cpp](C:/Users/benco/dev/BODAQS/firmware/src/Routes_Config.cpp)

### I2C/multi-bus plumbing

- [BoardProfile.h](C:/Users/benco/dev/BODAQS/firmware/src/BoardProfile.h)
- [BoardProfile.cpp](C:/Users/benco/dev/BODAQS/firmware/src/BoardProfile.cpp)
- [I2CManager.h](C:/Users/benco/dev/BODAQS/firmware/src/I2CManager.h)
- [I2CManager.cpp](C:/Users/benco/dev/BODAQS/firmware/src/I2CManager.cpp)
- [DisplayManager.cpp](C:/Users/benco/dev/BODAQS/firmware/src/DisplayManager.cpp)
- [PowerManager.cpp](C:/Users/benco/dev/BODAQS/firmware/src/PowerManager.cpp)
- [main.cpp](C:/Users/benco/dev/BODAQS/firmware/src/main.cpp)

## Multi-bus I2C work

Before adding the I2C sensor variant, the firmware was extended from a single implicit `Wire` bus to a small explicit multi-bus model.

### Board model

`BoardProfile` now supports:

- a small fixed array of I2C bus profiles
- `i2c_count`
- per-device `bus_index` for consumers such as:
  - display
  - fuel gauge

### Runtime model

`I2CManager` now:

- owns bus bring-up
- maps bus 0 to `Wire`
- maps bus 1 to `Wire1`
- provides bus lookup
- provides bus locking

This was added so future sensors like an AS5600 over I2C could be placed on a second bus if needed.

## AS5600 I2C variant implementation

### What was implemented

`AS5600StringPotI2C` was added as a sibling to the analog variant.

It currently:

- takes `i2c_bus`
- takes `i2c_addr`
- reads the AS5600 wrapped angle over I2C
- feeds the wrapped count into the shared `AS5600StringPotSensorBase`

`SensorManager` was updated so only analog-backed sensor types require `ain/pin`.

## Calibration behavior and fixes

### Shared calibration model

The intent was to keep a single `RANGE` calibration flow for both:

- simple analog pots
- multi-turn AS5600 string pots

For the AS5600 family, `RANGE` is interpreted as **unwrapped range**, not wrapped one-turn counts.

### Range tracking fix

An important bug was found early:

- the menu’s `RANGE` flow only sampled start and finish windows
- that meant turn crossings could be missed if the sensor moved multiple turns between those windows

This was fixed by continuously polling `currentRawCounts()` during `RangeActive` in:

- [MenuSystem.cpp](C:/Users/benco/dev/BODAQS/firmware/src/MenuSystem.cpp)

That allows wrapped sensors to accumulate turn crossings during the active range movement.

### ZERO calibration bug

Another real bug was found and fixed:

- the AS5600 base accepted a captured ZERO value
- but then threw it away and saved a fresh sample at finish time

This was fixed in:

- [AS5600StringPotSensorBase.cpp](C:/Users/benco/dev/BODAQS/firmware/src/AS5600StringPotSensorBase.cpp)

The menu toast was also changed to show the captured average that is actually saved.

### Wrap threshold issue

During testing, `RANGE` still appeared not to unwrap properly.

The live debug trace showed:

- unwrapped calibration counts were never exceeding one turn
- because the observed wrapped discontinuity was smaller than the configured `wrap_threshold_counts`

Conclusion:

- the shared unwrap logic was working
- but the threshold needed to be tuned for the actual observed jump size

This is a sensor/setup tuning issue, not a transport-specific architectural issue.

## Startup-turn behavior

We agreed on this startup model:

- runs begin with an assumption of turn 0
- however, `installed_zero_count` may be anywhere within the turn

That led to another fix:

- on first sample, the AS5600 base now initializes unwrapped counts relative to the phase of `installed_zero_count`
- so if wrapped position at startup is below the installed-zero phase, it is lifted into the next turn rather than treated as negative travel

This behavior lives in:

- [AS5600StringPotSensorBase.cpp](C:/Users/benco/dev/BODAQS/firmware/src/AS5600StringPotSensorBase.cpp)

## What was learned during I2C debugging

### 1. Early “quantized” digital readings

When the AS5600 was first tested over I2C, the raw readings looked highly quantized / stair-stepped.

We investigated:

- firmware sample/storage path
- wrap logic
- `RAW_ANGLE` vs `ANGLE`
- I2C bus speed
- magnetic setup

### 2. Important debugging conclusion

The odd values were already visible in the sensor’s direct I2C debug read path, before:

- unwrapping
- `sampleValues()`
- queueing
- storage

So the problem was **not** in the path between sampling and storage.

### 3. `RAW_ANGLE` vs `ANGLE`

We temporarily instrumented the AS5600 to compare:

- `RAW_ANGLE`
- `ANGLE`

Result:

- both tracked each other closely
- so the stepped behavior was **not** caused by choosing the wrong register

That diagnostic instrumentation has since been removed.

### 4. DIR pin

At one point, `DIR` on the AS5600 was floating.

Tying `DIR` to a defined level improved behavior.

Takeaway:

- `DIR` must not be left floating

### 5. Pull-ups

The breakout was measured and found to already have about `10k` pull-ups from:

- `SDA` to `VCC`
- `SCL` to `VCC`

So “missing pull-ups” is probably not the primary issue.

### 6. Magnetic setup

There was strong discussion around magnet alignment and the possibility of distortion from the magnet being mounted directly on a ferromagnetic shaft.

Conclusions:

- brass or other non-ferromagnetic shaft material would help
- a non-magnetic carrier/spacer for the magnet is preferable to mounting directly on steel
- however, this was not the full explanation for the I2C-only issue, because:
  - the same suspect AS5600 behaved smoothly in analog mode under the same magnetic arrangement

That suggested the magnetic arrangement was not the whole story.

## The crucial discovery: address conflict

Eventually the fuel gauge behavior provided the key clue.

### Observed behavior

- the fuel gauge was not working while the AS5600 was on the I2C bus
- with the AS5600 disconnected, the fuel gauge returned on reboot

### Conclusion

This strongly indicated an I2C address conflict.

The key fact:

- `AS5600` fixed address: `0x36`
- `MAX17048` fixed address: `0x36`

So the plain AS5600 and the MAX17048 cannot share the same I2C bus.

This also explains why some of the AS5600’s digital I2C readings were suspect:

- the bus likely had two devices responding at the same address

### Fuel gauge board-profile fix

During this work, the active S3 board profile’s fuel-gauge address was corrected back to `0x36` in:

- [BoardProfile.cpp](C:/Users/benco/dev/BODAQS/firmware/src/BoardProfile.cpp)

Earlier it had been set to `0x32`, which was misleading/wrong for the MAX17048 on the active board.

## What is currently true

### Firmware state

- Multi-bus I2C support exists in the firmware.
- `AS5600 String Pot (I2C)` exists and instantiates.
- Shared unwrap logic and calibration logic exist.
- ZERO capture bug has been fixed.
- Continuous RANGE tracking during active calibration has been fixed.
- Temporary debug instrumentation used during diagnosis has been removed.
- Fuel gauge address in the active S3 board profile has been corrected to `0x36`.

### Hardware constraint

On the current hardware, the plain AS5600 over I2C cannot be used on the same bus as the MAX17048 because they share address `0x36`.

## Recommended next steps for future work

If AS5600-over-I2C is to be pursued on this hardware, the realistic options are:

1. Put the AS5600 on the second I2C bus
- The firmware is now set up to support this.
- Hardware changes are needed.

2. Use an I2C mux/switch
- More complexity, but avoids address conflict.

3. Keep using the AS5600 in analog mode
- This already worked acceptably in testing.

4. Use a different sensor / variant
- For example a device with a configurable or different I2C address.

## Notes for another chat

The most important context to carry forward is:

- The firmware work is mostly done.
- The remaining blocker is not “how do we code AS5600 over I2C?” so much as “how do we avoid the `0x36` address conflict with the MAX17048?”
- If future work continues on AS5600 over I2C, the most promising path is to put it on bus 1 and stop trying to share bus 0 with the fuel gauge.
