BODAQS 0.6.2-beta: A8 v1.0 and v1.1 only
Tag: firmware-v0.6.2-beta
Firmware identity: bodaqs_a8-0.6.2-beta

Update an existing logger: flash bodaqs_a8-0.6.2-beta.bin at 0x10000.
Blank/erased logger: flash bodaqs_a8-0.6.2-beta-full.bin at 0x00000.
The full image overwrites flash settings in its padded NVS region.
Application-only updates preserve existing flash settings. SD files are separate.
Components: bootloader 0x00000, partitions 0x08000, application 0x10000.
The partition layout is unchanged from the previous A8 beta.
Do not install these images on RC3 or Prototype F.

The RTC is detected automatically: RV-3028 on v1.0, ISL1208 on v1.1.
No logger settings migration is required. See RELEASE_NOTES_DRAFT.md.
The CAN-FD feature branch is not included.

SHA256SUMS.txt covers all four binaries. BUILD_MANIFEST.json
records the exact source build commit, libraries, memory use and image hashes.
The release tag points to the packaging commit containing the same firmware source.
BUILD_LOG.txt and HOST_TEST_LOG.txt contain passing automated validation.
The owner tested the RTC development firmware on both A8 revisions.
Release version-number metadata was rebuilt afterwards. No device was flashed
during release packaging. Detailed retention/accuracy measurements are not supplied.
