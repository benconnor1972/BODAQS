# Prepared single-node IMU smoke images

Prepared 2026-11-05 for the user-authorized happy-path bench attempt. Follow the
[operator steps](CAN-FD_Single_Node_IMU_Smoke_Test.md). No device access, upload,
flash, remote publication or issue change was performed.

## Artifact locations and identity

- Directory: `C:/Users/benco/dev/BODAQS-worktrees/single-node-imu-smoke`.
- ZIP: `C:/Users/benco/dev/BODAQS-worktrees/single-node-imu-smoke.zip`.
- ZIP SHA-256: `bd600dfa54e1f0fc8c75203e1967156fbe63613a35f122db0626d8133bc5c696`.
- Manifest SHA-256: `6b9ec2347f79d0cd6d04a09d4731222115c7e61f61ffbd9bcfcb6d8c4d5eb19b`.

All 16 entries in the directory's `SHA256SUMS.txt` were independently checked.
The ZIP contains that inventory and all corresponding files, including the
standalone `SMOKE_TEST.md` instructions.

| Component | Source/build identity | Image SHA-256 |
|---|---|---|
| A8 logger smoke | `d70ba1bae96f79e258b7a3478a08bf1489eb1683`, `bodaqs_s3_mini_n4r2_imu_smoke` | `6f04870e466c4f4e0a76ff806ee8ff1882f98927f0e79f3d9e929161311052b2` |
| G3518 master acquisition | verified source `8871ae488ed374843efcae2da3e1024e633d86ff` | `1745153413959a8913de4a4912036a41c53c7cec8144c63fd30b65db8f87f163` |
| G3507 node acquisition | same verified source/profile | `703ef1a697db2eb47e3b7ab42c7911ff16c9b2ad967a066a3e55575ee40fed54` |

The master/node inputs under `firmware/can-fd` are unchanged through the smoke
commit; their already passing acquisition builds were verified and reused.
Both run 1 Mbit/s arbitration and 4 Mbit/s data. The logger build was refreshed
after committing the smoke source. Additional edits after that commit are build
evidence documentation only.

## Software checks

- Independent admission fixture passes one-node experimental admission while
  keeping `qualified=false`; rejects extra IMUs, other active logical sensors
  and ADC work. The normal unqualified production evaluator still rejects.
- Actual coordinator/control lifecycle fixture passes with the smoke compile
  flag and without supplying synthetic qualified scheduling costs.
- Complete firmware host/runtime suite passes, including existing production,
  four-node, writer/reader, control and storage regressions plus the smoke case.
- Smoke A8 target build passes: RAM 260332 bytes, flash 2017805 bytes.
- Normal guarded A8 target also builds successfully.
- Distinct firmware-name and unqualified-mode strings were verified in the
  produced smoke image. API/UI/header/footer explicitly disclose the exception;
  unmeasured occupancy/drain metrics are null in the smoke API.
- Fresh independent Standards and Spec reviews found no actionable findings.

Local logs are included in the bundle, normalized from PowerShell redirection to
UTF-8. Logger flash offsets were checked against the selected PlatformIO board,
partition CSV and installed framework's extra-image settings. Firmware files are
separate segments, not a merged image that fills the NVS gap.

## Qualification scope

This is an explicitly unqualified single-node exception, not an installed
qualified scheduling profile. Exactly one unmuted remote IMU and no other active
logical sensors/ADC work are permitted for remote acquisition. Existing link,
configuration, allocation, storage barrier, lease, STOP and cleanup guards remain.
Normal production admission and desired sampling settings are unchanged. Measured
timing, alignment, throughput and physical fault coverage are not established;
qualification #175/#176 remains open and unexecuted. Multi-node smoke testing is
a subsequent stage requiring its own explicit experimental scope.
