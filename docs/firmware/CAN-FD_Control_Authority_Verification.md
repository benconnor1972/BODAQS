# Control authority verification (#157)

The idle logger inspects nodes before attempting challenge/bind. Each logger
initialization creates a nonzero platform-random 64-bit session (bounded entropy
failure leaves authority disabled). Node challenge allocation starts from 64 bits
of TRNG entropy and advances without reuse until exhaustion. Runtime entropy is
captured one ready word per main-loop turn; it never waits in CAN dispatch.
The original board/boot initialization is preserved.

Binding and release update only authority and fitted-endpoint eligibility epochs.
They preserve configuration hardware, accepted generation, accepting session and
applied revision. Identical retries neither rewind the mutation high-water mark
nor advance epochs. The release tombstone authorizes only its identical retry.

`bodaqs_control_authority_admit` validates the next sequence against the active
session. A future mutation service must cache pending evidence using `complete`
at admission, publish `pending_operation` in the shared node view, and replace the
cached evidence at completion. Read IDs never consume mutation sequence state.
`GET_OPERATION` targets a nonzero session and sequence; unavailable/superseded
outcomes are query results, not evidence of rejection or non-application.

The diagnostics API reports `logger_session_id`, acknowledgement-based
`authority_bound`, `authority_observed_current`, reason and confirmation time.
Current observation additionally requires matching boot/session and observation
time after confirmation. `configuration_reconciled` remains false. Effective
snapshot accepting-session/generation/revision fields retain their own provenance.
`CanMasterManager::releaseControlAuthority(address)` is an idle-only integration
API. There is no new HTTP mutation endpoint.

Live node clock-fault transitions use `bodaqs_control_node_update_clock_fault`
to advance every fitted endpoint epoch once, including fault clearance. Repeated
unchanged health consumes no epochs. If any fitted epoch cannot advance, the
node latches epoch exhaustion until reboot and rejects inspection, snapshots and
authority requests with reason 22; boot/session/epoch identities never wrap.
Captured pages remain immutable, and the observer rejects their old health as
current when the final fresh endpoint epoch differs. No wire format changes.
The authority client owns revocation after a fresh observed session mismatch via
`bodaqs_control_authority_client_observe_session`; observations never grant binding.

## Automated checks

- `gmake -C firmware/can-fd/common/test test`: codec, master service, SPI/CAN,
  authority lifecycle, five-second expiry/wraparound, retained retries, guards,
  sequence/query scoping, and lost bind/release CAN replies under real retries.
- `python firmware/tools/test_control_authority_api.py`: production JSON helper
  with real ArduinoJson, including full 64-bit IDs and stale/reset observations.
- TI MSPM0G3507 node and MSPM0G3518 master builds; PlatformIO A8
  `bodaqs_s3_mini_n4r2`. Builds do not prove physical timing or entropy quality.

## Manual device checks (not performed)

Record board revisions, firmware commit, CAN wiring/termination and instruments.
Cold boot and debug reset each device; confirm nonzero changed boot/session IDs,
old-boot rejection, cleared bound/current diagnostics and eventual fresh binding.
Observe idle GET_STATE and endpoint descriptors before and after bind/release;
only authority/eligibility epochs should change. Check IMU registers and acquisition
signals independently to demonstrate no sensor hardware effects. Drop the first
bind/release reply and confirm identical retry convergence, unchanged sequence
history and one epoch advance. Delay bind beyond five seconds and verify explicit
challenge rejection. Inject acquisition/lease/recording/pending guards in a debug
build; confirm rejection and unchanged hardware. Simulate TRNG readiness failure
and verify responsive inspection with binding unavailable. Verify bound versus
observed-current API transitions on node/master reset, disconnect and another
session taking authority. Repeat queue-load and stack measurements from the
inspection verification guide; no flashing or physical validation is automated.
