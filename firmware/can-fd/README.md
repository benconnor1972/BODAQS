# BODAQS CAN-FD firmware

This directory contains firmware that runs on the MSPM0 devices in the
BODAQS CAN-FD network. It is intentionally separate from the ESP32 logger
PlatformIO project in the parent directory.

## Layout

- `common/protocol`: portable logger-to-master SPI protocol code
- `common/network`: portable CAN-FD codecs and four-address node inventory
- `common/test`: host tests for both portable protocol layers
- `master`: MSPM0G3518 master-daughterboard firmware
- `node`: MSPM0G3507 IMU-only sensor-node firmware

The current master firmware provides the logger SPI interface and the first
physical-network slice:

- the 5 V converter is enabled at startup, but both protected trunk switches
  remain off until the first valid logger probe or status request is processed;
  the front switch is then enabled and the rear switch stays disabled;
- the green status LED blinks while firmware is alive;
- reset cause, power-fault inputs, and SPI counters are visible to a debugger;
- SPI0 operates as a mode-0 peripheral on the production-board pins; and
- `ProbeRequest` is answered with the version-1 `IdentityResponse` expected by
  the logger firmware;
- `StatusRequest` reports reset, uptime, power-fault, SPI recovery, and reserved
  CAN/queue diagnostics without enabling trunk power; and
- DMA rearming is synchronized to chip-select release, and malformed SPI slots
  reset and re-arm the transport; decode-error categories and chip-select
  release timeouts are visible to a debugger; and
- CANFD0 is initialized on PA26/PA27 for 500 kbit/s arbitration and 2 Mbit/s
  CAN-FD data with bit-rate switching, using a 40 MHz SYSPLLCLK1 kernel clock
  derived from the external crystal;
- a nonce-changing discovery request is transmitted every five seconds; and
- node announcements and one-second status frames populate a bounded
  four-address inventory, with stale, duplicate, malformed, incompatible and
  queue diagnostics visible through `gMasterRuntimeInfo` and `gNodeInventory`;
  and
- both controllers initiate standards-required bus-off recovery after a
  one-second quiet interval, so connecting a peer after single-board operation
  restores communication without resetting either board.

The IMU-only firmware uses the production MSPM0G3507SRHBR pins. It reads the
two address straps, releases the CAN transceiver from standby, announces after
boot and in response to discovery, and sends a phased status frame once per
second. Its current hardware identity advertises only the fitted IMU endpoint;
IMU acquisition is not yet enabled.
`gNodeRuntimeInfo` exposes its identity, address, traffic, decode, queue, clock,
error-passive and bus-off-recovery diagnostics.
The address inputs use the MCU's internal pull-downs because the IMU-only board
does not fit the external pull-down resistors present on the full node: open
address jumpers select zero and each closed jumper sets its corresponding bit.

The production clock configuration allows the external 16 MHz crystal the
maximum HFXT startup interval (approximately 16.32 ms) before validating it and
switching the CPU to the 80 MHz PLL clock. Hardware testing showed that the
shorter 0.64 ms interval was insufficient on the first master board.

The application deliberately remains in RUN mode between SPI transactions.
Entering `WFI` exposed MSPM0Gx51x erratum `SPI_ERR_02`: the first SPI bits after
waking were shifted and every fetch slot failed CRC. Lower-level debug resets
can also retain HFXT and SYSPLL state, so startup returns MCLK to SYSOSC and
waits for both retained sources to stop before running the generated clock
initialization.

General trunk power policy, sensor configuration, synchronization, sample
transport and logger-side inventory transfer are not enabled in this slice.
For the physical discovery test, the front branch is enabled only after
successful logger communication; front-fault status remains available over SPI
and in `gMasterRuntimeInfo`.

## Toolchain

The project is tested with MSPM0 SDK 2.11.00.07, SysConfig 1.28.1, and TI Arm
Clang 5.1.1 LTS. Set `MSPM0_SDK_INSTALL_DIR` when building; the SDK itself is
not vendored in this repository.

From PowerShell:

```powershell
& 'C:\ti\ccs2101\ccs\utils\bin\gmake.exe' `
  -C .\can-fd\master\ticlang `
  MSPM0_SDK_INSTALL_DIR=C:/ti/mspm0_sdk_2_11_00_07

& 'C:\ti\ccs2101\ccs\utils\bin\gmake.exe' `
  -C .\can-fd\node\ticlang `
  MSPM0_SDK_INSTALL_DIR=C:/ti/mspm0_sdk_2_11_00_07
```

The resulting `bodaqs_can_master.out` and `bodaqs_can_node.out` can be loaded
with CCS through an XDS110 probe. The production master target is MSPM0G3518
and the IMU-only node target is MSPM0G3507; use the matching target configuration
for each board.

Run the portable protocol test with a host C++ compiler:

```powershell
$env:PATH = 'C:\msys64\ucrt64\bin;' + $env:PATH
& 'C:\ti\ccs2101\ccs\utils\bin\gmake.exe' `
  -C .\can-fd\common\test test `
  CXX=C:/msys64/ucrt64/bin/g++.exe
```

