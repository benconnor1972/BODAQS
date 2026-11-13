# r23: one observation run, master change only

Read INVESTIGATION.md for hypotheses, exact metric meanings and decision bounds.
Require BUILD_MANIFEST.json status=passed before use. No flashing was performed
while preparing this kit. Keep the r21 idle-fetch logger, all four node images,
current wiring and SD card unchanged. Controlled storage-stall tests stay deferred.

1. With logging stopped, install `artifacts/master-diagnostic/bodaqs_can_master.out`
   in CCS using the usual MSPM0G3518 target. This is the only new firmware.
   Verify `gMasterOptimizationInfo=[1,0,0]`, `gMasterBoundaryReserve=2`, and
   `sizeof(gMasterBatchInfo)=1448`. The diagnostic version becomes1 after entry;
   an all-zero block immediately after boot is expected.
2. Use the unchanged `Configurations/C_4imu_adc_off.txt` (private credentials).
   Restart master/nodes first, then logger. Run/F8 the master and allow at least
   60seconds for reconciliation. Do not halt any board while acquiring/cleaning up.
3. Save complete serial output, start normally, require `streams=9`, no excluded
   participant or early failure, and about105seconds of acquisition after running.
   Stop normally. Wait for file closure, FLOW and the PIPE `type=end` line.
4. Before another recording, export the new block. Close/disconnect the CCS IDE
   target session if it prevents the scripting target connection. From PowerShell:

```powershell
& 'C:/ti/ccs2101/ccs/scripting/run.bat' 'C:/Users/benco/dev/BODAQS-worktrees/imu-batch-investigation-r23-r2/export_batch_diagnostics.js'
```

The exporter briefly connects/suspends the stopped master, loads symbols only,
reads RAM, saves `Results/01-observe/attempt1/master-batch.bin`, and resumes.
It never flashes or resets. If export fails, preserve the error and stopped state;
do not repeat a recording just to get the file. Existing exports are not overwritten.

5. Put exactly one finalized BDQ, `serial.txt`, actual exported `loggercfg.txt`,
   and available `ccs.txt` (gMasterDrainInfo/gMasterRuntimeInfo as before) beside
   that binary in `Results/01-observe/attempt1`. The binary is essential to the
   new questions. CCS JSON is supplementary; do not round binary identity values.
6. Read out to a fresh directory outside the inputs:

```powershell
& 'C:/Users/benco/dev/BODAQS-worktrees/drain-capacity-evidence/spi-prototype/tool-venv/Scripts/python.exe' -B 'C:/Users/benco/dev/BODAQS-worktrees/imu-batch-investigation-r23-r2/assessor-source/firmware/tools/assess_batch_investigation.py' --case 'C:/Users/benco/dev/BODAQS-worktrees/imu-batch-investigation-r23-r2/Results/01-observe/attempt1' --output 'C:/Users/benco/dev/BODAQS-worktrees/imu-batch-investigation-r23-attempt1-report'
```

The tool retains strict BDQ/primary failures and returns1 if they persist; a
valid batch diagnostic does not turn known loss into a pass. It checks the exact
binary context/session/recording/master-boot against all four BDQ sources, and
retains unavailable/mismatched evidence explicitly. The unchanged logger recipe
alone cannot attest the installed master image.

Compare against REFERENCE_4IMU.json, not synthetic raw-byte arithmetic: 5852.90
first100sreadings/s;54.02%whole-source missing;4804primary drops. This is an
observer run, not a claimed optimization. Review seal causes, batch fill,
sealed-to-ACK residence and all-prepared-to-ACK delay, repeated preparations,
PIPE/FLOW, storage pressure and all four final boundaries. Histograms include
cleanup, and software preparation is not observed physical SPI transmission.

No sweep follows automatically. Select one small fix only if evidence supports
at least10% plausible useful gain, primary-loss removal or a correctness repair;
otherwise carry the measurements to redesign. If observation changes performance
materially, one rollback control can be considered before interpretation.
Rollback master: `artifacts/rollback-master/bodaqs_can_master.out`; the logger and
nodes never change. Preserve original evidence even if the run fails early.
