BODAQS 0.6.1-beta: RC3, A8 and Prototype F
Built: 11 October 2026
Status: beta images; release notes draft, physical acceptance pending.

Application updates: flash the matching board .bin at 0x10000.
Blank/erased logger: flash its matching -full.bin at 0x00000.
Separate components: bootloader 0x00000, partitions 0x08000, application 0x10000.
Do not mix board variants.

Board identities:
- RC3: bodaqs_v1RC3-0.6.1-beta
- A8: bodaqs_a8-0.6.1-beta
- Prototype F: bodaqs_4f-0.6.1-beta

Input column, configuration warnings/Enter restart, automatic persisted
BDQ v2 selection, optional startup reports on SD (General page, default off),
enlarged queues, ADC waiting and stack-safety fixes.
Whole-FIFO fixed two-deferral scheduler, I2C transfer priority 2.
All images enable the latest startup recovery diagnostics and Arduino HAL
BMI270 identity probes. The long startup speed-comparison probe is disabled.

SHA256SUMS.txt covers all 12 binaries. BUILD_MANIFEST.json records settings,
targets, libraries, sizes, hashes and validation. BUILD_LOG.txt and
HOST_TEST_LOG.txt contain the validation output.

Canonical draft: docs/firmware/Firmware_0.6.1-beta_Release_Notes_Draft.md
RELEASE_NOTES_DRAFT.md is a packaged copy.
