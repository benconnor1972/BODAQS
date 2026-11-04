# Master long-HFXT-startup diagnostic

This diagnostic tests the production clock path while allowing the external
16 MHz crystal substantially longer to start. It uses an HFXT startup setting
of 255 (approximately 16.32 ms), then runs the CPU at 80 MHz from the SYSPLL and
blinks the production-board status LED with a one-second complete cycle.

The 5 V converter and both CAN-trunk load switches remain disabled. SPI and
CAN-FD are not configured by this image.

Build from PowerShell with:

```powershell
& 'C:\ti\ccs2101\ccs\utils\bin\gmake.exe' `
  -C .\can-fd\master\diagnostics\long_hfxt_startup\ticlang `
  MSPM0_SDK_INSTALL_DIR=C:/ti/mspm0_sdk_2_11_00_07
```

The resulting image is:

```text
ticlang/bodaqs_can_master_long_hfxt_startup_test.out
```

`gLongHfxtStartupTestInfo` is visible to the debugger. Its interrupt counter
increments every 100 ms and its toggle counter increments every 500 ms.

If the LED blinks, the external crystal and PLL path work with the longer HFXT
startup interval. If execution still stops in
`DL_SYSCTL_setHFCLKSourceHFXTParams()`, the crystal path needs physical
inspection or oscilloscope testing.

