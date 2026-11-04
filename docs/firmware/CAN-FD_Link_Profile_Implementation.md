# Explicit CAN link profiles (#173)

The node and master share `common/network/bodaqs_can_link.h`. The explicit
`CAN_LINK_PROFILE` target-build selector accepts `bringup` (default,
500 kbit/s arbitration / 2 Mbit/s data) or `acquisition` (1 Mbit/s / 4 Mbit/s).
Select the same profile on both boards. Rates never change during a recording.

SysConfig retains the original bring-up initialization. Before application TX,
the shared startup adapter applies the selected timing in software-init mode,
reads back all eight timing fields and returns to normal mode. The generated
source is not edited. A failed selection leaves application TX unavailable;
it does not fall back silently. Build rules rebuild both profile consumers when
switching profiles, including switching back without cleaning.

The documented 40 MHz MCAN clock gives encoded nominal/data segment tuples
`(0,62,15,15)/(0,14,3,3)` for bring-up and
`(0,30,7,7)/(0,6,1,1)` for acquisition (prescaler, segment 1, segment 2, SJW).
These are register configurations, not measured bit timing or signal integrity.
The existing SysConfig transmitter-delay compensation settings remain unchanged
and require qualification at the selected rate.

Existing master identity and node announcement capability words report the
actual normal-mode register selection: bit 28 means bring-up; bit 29 means
acquisition. Neither bit or both bits means unknown. Other capability bits
remain unchanged; old readers preserve unknown bits. Matching these fields
establishes explicit selected-profile compatibility, never electrical or
scheduling qualification. Missing peers and legacy capability words cannot
establish compatible rates by inference.

From the repository root, select the target and link explicitly:

```powershell
& 'C:/ti/ccs2101/ccs/utils/bin/gmake.exe' -C firmware/can-fd/node/ticlang `
  MSPM0_SDK_INSTALL_DIR=C:/ti/mspm0_sdk_2_11_00_07 CAN_LINK_PROFILE=acquisition
& 'C:/ti/ccs2101/ccs/utils/bin/gmake.exe' -C firmware/can-fd/master/ticlang `
  MSPM0_SDK_INSTALL_DIR=C:/ti/mspm0_sdk_2_11_00_07 CAN_LINK_PROFILE=acquisition
```

Use `CAN_LINK_PROFILE=bringup` to build the preserved slower profile. These
commands compile only. Host register-boundary tests cover exact values,
switching back, unknown/contradictory capabilities, compatibility and failure.
Both target builds pass for both profiles. Physical #175/#176 remains deferred;
the profile capability bits do not authorize acquisition without the separate
complete resource and qualification checks.
