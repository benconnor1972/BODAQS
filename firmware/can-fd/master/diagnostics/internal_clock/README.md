# Master internal-clock diagnostic

This diagnostic isolates the MSPM0G3518, status LED, and basic power rails from
the external 16 MHz crystal circuit. It runs from the device's internal 32 MHz
SYSOSC and blinks the production-board status LED with a one-second complete
cycle.

The 5 V converter and both CAN-trunk load switches remain disabled. SPI and
CAN-FD are not configured by this image.

Build from PowerShell with:

```powershell
& 'C:\ti\ccs2101\ccs\utils\bin\gmake.exe' `
  -C .\can-fd\master\diagnostics\internal_clock\ticlang `
  MSPM0_SDK_INSTALL_DIR=C:/ti/mspm0_sdk_2_11_00_07
```

The resulting image is:

```text
ticlang/bodaqs_can_master_internal_clock_test.out
```

`gInternalClockTestInfo` is visible to the debugger. Its interrupt counter
increments every 100 ms and its toggle counter increments every 500 ms.

