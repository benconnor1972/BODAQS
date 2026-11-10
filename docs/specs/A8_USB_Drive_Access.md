# A8: writable USB SD-card access in UPLOAD mode

Status: published as [GitHub issue #191](https://github.com/benconnor1972/BODAQS/issues/191).
Product behavior and testing boundaries approved. Implementation checkpoint:
[A8 USB feasibility](../firmware/A8_USB_Drive_Feasibility.md).

## Problem Statement

A8 users need to transfer recordings without removing the SD card or relying on
Wi-Fi. A USB cable should let them use their computer's normal file tools and
Import Manager while keeping recording and computer access mutually exclusive.
They also need to return to recording from the logger without a mandatory
computer-side eject procedure.

## Solution

Expose the A8 SD card as a writable USB mass-storage drive automatically when a
USB data connection and UPLOAD mode are both present. Support Windows, macOS,
and Linux with their built-in drive support. Give USB exclusive card access,
coordinate Wi-Fi transfers, and reclaim local storage when leaving UPLOAD mode.

Automatic reclaim uses a visible delay and observed inactivity to reduce the
risk of interrupted transfers. It cannot guarantee that computer write caches
have been flushed. Provide clear help and retain optional computer-side ejection.
Import Manager discovers the mounted logger and copies recordings locally before
importing them through the existing pipeline.

## User Stories

1. As an A8 user, I want to connect a USB data cable in UPLOAD mode, so that my computer can access the SD card without removing it.
2. As an A8 user, I want a cable connected before UPLOAD entry to work automatically, so that connection order does not matter.
3. As an A8 user, I want normal mode to keep the drive unavailable, so that connecting USB does not expose recording storage.
4. As an A8 user, I want recording to remain prohibited in UPLOAD mode, so that recording cannot conflict with file transfers.
5. As an A8 user, I want UPLOAD entry refused during recording, so that an active recording is not interrupted.
6. As a Windows user, I want built-in drive access, so that no special driver or BODAQS application is needed to browse files.
7. As a macOS user, I want built-in drive access, so that I can use ordinary file tools.
8. As a Linux user, I want built-in drive access, so that I can use ordinary file tools.
9. As an A8 user, I want to copy recordings from the drive, so that I can keep and share them locally.
10. As an A8 user, I want to add and delete files, so that the mounted card behaves as a writable drive.
11. As an A8 user, I want an existing Wi-Fi file transfer to finish before USB takes over, so that connecting a cable does not interrupt it.
12. As an A8 user, I want new SD-dependent Wi-Fi operations paused during handoff and USB ownership, so that both sides cannot alter the filesystem together.
13. As an A8 user, I want status and controls that do not need SD access to remain available, so that I can monitor the logger and request mode changes.
14. As an A8 user, I want to leave UPLOAD mode on the logger without first ejecting on the computer, so that I can return to recording directly.
15. As an A8 user, I want a visible disconnecting delay, so that the pending transition is understandable.
16. As an A8 user, I want the logger to wait for transfer inactivity and finish received requests, so that it reduces the risk of interrupted writes.
17. As an A8 user, I want to cancel a waiting exit, so that I can finish a transfer before trying again.
18. As an A8 user, I want the logger to wait through sustained USB activity, so that a forced timeout does not cut off my transfer.
19. As an A8 user, I want concise help about finishing copies and optional computer-side ejection, so that I understand how to reduce data-loss risk.
20. As an A8 user, I want completed computer-side ejection to remain effective, so that the drive does not immediately reappear.
21. As an A8 user, I want cable reconnection or UPLOAD re-entry to restore an ejected drive, so that I can intentionally start another transfer.
22. As an A8 user, I want recording blocked until the card is successfully reclaimed, so that recording does not start on unavailable storage.
23. As an A8 user, I want a remount error and retry option, so that I can recover without automatic formatting or repair.
24. As an A8 user, I want card removal to report no media and show a clear message, so that an absent card is not treated as available storage.
25. As an A8 user, I want reinsertion to require a mode toggle or cable reconnection before USB exposure, so that a replacement card is not silently shared.
26. As an Import Manager user, I want mounted BODAQS cards discovered automatically, so that I do not need to configure changing drive paths.
27. As an Import Manager user, I want to choose a profile and destination once for a new logger, so that later connections reuse that association.
28. As an Import Manager user, I want manual folder selection as a fallback, so that I can import when automatic discovery is unavailable.
29. As an Import Manager user, I want recordings copied to a local inbox before processing, so that processing does not depend on the logger remaining connected.
30. As an Import Manager user, I want originals retained by default, so that importing does not implicitly delete my recordings.
31. As an Import Manager user, I want interrupted copies to be retryable and repeated discovery to avoid duplicate imports, so that reconnections do not cause loss or duplicate library entries.
32. As an A8 maintainer, I want USB serial diagnostics and firmware-update workflows preserved, so that drive support does not prevent maintenance or recovery.
33. As a BODAQS developer, I want development based on main and independent of CAN-FD, so that this feature can ship without unfinished CAN-FD work.

## Implementation Decisions

- Scope the new drive behavior to A8. Develop from main without incorporating
  the in-progress CAN-FD work; preserve existing behavior for other boards.
- Use the existing UPLOAD mode and logging gates. Do not persist UPLOAD across
  restart: a cable alone must not expose the card after reboot.
- Use the A8's native ESP32-S3 USB hardware. Mass storage requires USB-OTG rather
  than the currently selected hardware USB Serial/JTAG controller. Preserve
  serial diagnostics and firmware updating, evaluating composite CDC plus MSC.
- Establish explicit storage ownership and transition states through the upload
  and storage managers. All SD consumers must honor them, including web/API file
  handlers, status queries, background archive work, and automatic remount logic.
  Locally unmounted USB-owned media is not itself a storage fault.
- Before exporting storage, complete existing SD operations and relinquish local
  filesystem access. When a Wi-Fi file transfer is active, finish it, reject new
  SD operations, and show "Waiting for Wi-Fi transfer." Non-SD status and controls
  remain available. Wi-Fi file access resumes after local ownership is restored.
- Expose the actual SD card as writable mass storage. The computer has exclusive
  filesystem access while exported; no simultaneous local filesystem access is
  permitted even for seemingly harmless status reads.
- On exit request, show "Disconnecting USB..." for at least three seconds and
  require one second without USB reads or writes before disconnecting. Complete
  any in-flight request; activity postpones disconnect, with no forced transfer
  timeout. Keep the UI responsive and allow cancellation back to UPLOAD mode.
  Background host traffic counts as activity and may extend the wait.
- Disconnect USB storage before remounting locally. Permit normal mode and
  recording only after successful reclaim. On remount failure, remain in UPLOAD
  mode, block recording, display a storage error, and offer retry. Never format
  or repair automatically.
- Update all UPLOAD exit callers to represent a pending transition truthfully.
  Existing immediate-success behavior must not claim completion prematurely.
  Document any changed HTTP or module-interface contract and update its consumers.
- On host eject or cable loss, reclaim locally while retaining UPLOAD mode. After
  host eject, suppress re-exposure until reconnect or UPLOAD exit and re-entry.
  Detect host ejection behavior on each supported operating system.
- Physical card removal during USB access reports no media and a visible removal
  message. Reinsertion alone cannot export it again; require a mode toggle or
  cable reconnect. Reclaim failures follow the same visible error policy.
- Add cross-platform mounted-volume acquisition to Import Manager. Existing
  folder-source processing moves inputs through staging and is not a direct
  acquisition adapter for mounted logger cards. Copy eligible recordings into a
  local inbox, expose only completed copies to import, and reuse existing import
  validation and deduplication behavior. Keep runtime state and outputs local.
- Add a small logger-written identity file as a versioned interchange contract,
  describing logger identity and the recording location. Discover it on mounted
  volumes, collect profile/destination selection once, and remember the association.
  Offer manual folder selection. Validate identity and paths as untrusted input.
  Exact schema and association-key handling remain implementation design work;
  account for logger renaming, multiple devices, and changing mount paths.
- Retain original recordings by default. Automatic cleanup is not part of this
  feature; retries must not import incomplete local copies or duplicate successes.
- Add web help explaining that copies should finish before exit and optional
  computer-side eject offers better protection. Use short OLED status text and no
  per-exit confirmation prompt. Never describe the delay as a guarantee that
  computer write caches have been flushed.
- Validate a narrow USB/SD feasibility implementation before choosing raw SDMMC
  integration or a framework upgrade. The locally installed Arduino-ESP32 2.0.17
  has USBMSC but lacks newer SD_MMC raw-sector APIs; the platform is not pinned.
  Current upstream examples cannot be assumed compatible. Document and reproduce
  the selected build toolchain and evaluate any upgrade separately.

## Testing Decisions

The following test boundaries were confirmed during specification review.
Test external behavior and independently expected results, not private state layout,
callback counts, or a duplicate implementation of the state machine.

- **Primary acceptance boundary: complete A8-to-computer workflow.** Use a real A8
  and its normal controls, public status/API, mounted drive, and Import Manager.
  Verify observable file contents and mode/storage availability across Windows,
  macOS, and Linux. Real-device testing is required for enumeration, host caches,
  SDMMC behavior, electrical USB behavior, serial, and flashing; mocks cannot
  establish these properties.
- **Firmware automation boundary: upload/storage coordination public interface.**
  Exercise mode requests, transfer activity, time passage, disconnection, and
  storage failures through a small high-level coordination interface with fake
  clock/transport/storage dependencies where necessary. Verify admission and
  completion behavior, logging gates, cancellation, and mutually exclusive card
  access. Reuse the existing host C++ harness, which compiles selected production
  modules against hardware stubs; extend it at this boundary rather than testing
  every USB callback independently. Existing tests do not yet prove USB ownership.
- **Import automation boundary: source acquisition through the import runner.**
  Use temporary mounted-volume fixtures and local inbox/library outputs, faking
  only operating-system volume enumeration where needed. Reuse pytest patterns
  from filesystem import tests and Wi-Fi source acquisition tests, including
  partial-to-final acquisition, duplicate-success handling, and failure recovery.
  Verify discovery, pairing persistence, manual fallback, copied contents, source
  retention, and no import of incomplete copies.
- Cover both cable/UPLOAD activation orders, normal-mode connection, rejection
  during recording, writable browse/copy/add/delete, host eject suppression,
  reconnect, return to logging, and the normal-mode default after restart.
- Check the three-second minimum and one-second quiet interval at their boundaries;
  reads and writes postpone disconnect, in-flight requests finish, sustained
  activity has no forced timeout, and cancellation restores usable UPLOAD behavior.
- Cover Wi-Fi handoff with an existing transfer, blocked new SD work, independent
  status/control access, and restoration after reclaim. Verify every SD consumer
  respects ownership, including background tasks and remount/status paths.
- Cover missing/full cards, card removal/reinsertion, cable loss, reset, media I/O
  failure, and remount failure/retry. Assert truthful status, blocked recording
  when storage is unusable, and no automatic format/repair.
- Verify discovery on all supported hosts, remembered pairing across changed mount
  paths, multiple loggers, malformed identity data, interrupted-copy retry, and
  repeated discovery without duplicate successful imports. Import ZIP and BDQ
  recordings already supported by the pipeline without changing their formats.
- Compare independently generated file contents/checksums for completed transfers
  in both directions and for recordings made after reclaim. Unexpected removal
  tests assess error handling; they do not prove protection for host-cached writes.
- Build A8 and relevant existing board targets; verify serial diagnostics, normal
  firmware updating, and recovery flashing. Run the affected host and Python
  suites. Record physical board, firmware/toolchain version, OS, and results for
  manual checks; distinguish unperformed checks from passing evidence.

## Out of Scope

- CAN-FD integration, changes to its in-progress firmware, or branching from it.
- Extending USB drive support to other logger board variants.
- Simultaneous firmware and host filesystem access, or concurrent SD-based Wi-Fi
  file transfer while USB owns the card.
- Guaranteed loss-free automatic ejection, flushing unseen computer write caches,
  or automatic filesystem repair/formatting.
- Mandatory computer-side ejection or a confirmation prompt on every mode exit.
- Automatic recording after reclaim, persistent UPLOAD mode across reset, or
  implicit deletion of imported source recordings.
- A recording format migration, a general Import Manager rewrite, or a framework
  upgrade unrelated to demonstrable USB/SD requirements.
- Publishing a release, flashing a user's device, or creating implementation
  tickets as part of preparing this specification.

## Further Notes

The product behavior was confirmed in the design interview. A short quiet period
is a best-effort interruption reduction measure, not a safe-eject guarantee.
Continuous host traffic can keep exit pending; cancellation is the escape path.

The implementation must start with feasibility evidence for the selected USB
controller and SD ownership approach. Identity schema details and asynchronous
API representation are technical design work within the agreed behavior, not
claims of existing support. Any change to the agreed product behavior must be
raised explicitly.

