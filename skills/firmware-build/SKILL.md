---
name: firmware-build
description: "Build firmware artifacts, diagnose an authorized device connection, or flash an explicitly authorized target."
---

# Firmware build and device work

Read `docs/agents/firmware-validation.md` for offline validation, CI and candidate
commands, and `firmware/platformio.ini` for environments. Preserve the active
handoff's worktree, target, publication scope and physical debt. Select the branch
below from the user's requested action; a build ends at local artifacts.

## Build or validate locally

1. Select the explicit environment/board from the request, handoff or repository
   configuration. Reuse an existing selection without asking again.
2. Check tools/SDK with offline candidate preflight for target builds, or use
   host mode for validation without a TI SDK.
3. Build the selected target, for example
   `pio run -d firmware -e bodaqs_s3_mini_n4r2`. TI node/master builds use their
   `ticlang/makefile`, SDK and explicit `CAN_LINK_PROFILE`. The candidate runner
   builds both profiles and preserves separate artifact identities.
4. Run relevant checks and report exact source, environment, artifacts and
   remaining qualification. Stop at local artifacts for build-only work.

For `firmware/build.sh`, `list`, `build [env]` and `merge [env]` are local
operations. Its generic `bodaqs-firmware.bin` is overwritten by another target;
retain per-target names/identities. `check` and `detect` access devices and belong
to the diagnostic branch below, rather than offline preflight.

## Diagnose a device connection

Reach this branch only for an authorized device diagnostic. Reuse a selected
port. `build.sh check` probes the chip and `detect` scans/probes ports; use them
only within the authorized device scope. Report observed board/port/identity and
diagnosis. A diagnostic does not authorize upload.

## Flash

Reach this branch only when flashing is authorized. Resolve the explicit target
environment, board and port from the session; clarify only missing information.
Build and verify that target, then use `build.sh flash [env] --port PORT` or its
explicit upload command. Report the uploaded image/source and result. Software
checks do not qualify physical operation.

## Build configuration

For requested changes to environment, port, baud, offsets or output names, read
[configuration reference](references/configuration.md). Inspect actual
`firmware/build.sh`, `firmware/build.conf` when present, and `platformio.ini`
rather than caching defaults here. Configuration changes do not authorize device
access or remote publication.
