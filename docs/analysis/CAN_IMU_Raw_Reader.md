# CAN IMU raw BDQ reader

The Python raw reader recognizes `acquisition.payload_schema` values
`bodaqs.can_imu6.v1` and `bodaqs.can_timing_evidence.v1`, using the byte layouts
in [the acquisition transport contract](../firmware/CAN-FD_Acquisition_Transport_Contract.md#6-persisted-schemas-28-byte-sample-and-224-byte-companion).
Both retain the existing `fixed_mixed_v2` BDQ envelope. Existing BMI records
keep their previous interpretation.

`iter_bdq_stream_records(path, stream)` yields the declared numeric fields
without scaling or resampling. It preserves unknown numeric event kinds,
reasons and masks. A zero payload is meaningful only when the corresponding
validity bit is present. Wider bounds and reception ordinals remain explicit
low/high uint32 fields; combine them as `(high << 32) | low` using integers.

The catalog must declare every meaningful field at the contract offset/type,
without overlaps or channels in reserved bytes. Sample segment IDs must be
nonzero. Source sequence can restart in a new explicit segment; within a
segment the existing modulo sequence-order rule applies. Companion reserved
bytes must be zero. No event-kind whitelist discards future numeric evidence.

`bdq_to_stream_dataframes(path)` retains raw axes, source segment references,
prefix clocks and all companion fields. New sample `continuity_segment` is
the explicit source segment. The raw path does not infer clock resets or tick
wraps, fit receive times, or infer acquisition times from companion creation
ticks. `clock_epoch`, `native_tick_unwrapped` and `native_time_s` are unknown;
no logger `time_s` is produced for these new streams. Frame
`bdq_clock_alignment` attributes report unknown mapping. Native clock IDs and
provenance are retained in `bdq_stream_descriptor`; log metadata retains the
full descriptor under `secondary_streams[stream_key].descriptor` and the full
catalog under `bdq.stream_catalog`. Generic observations do not override this
explicit unknown state. Primary-interval trimming leaves these raw streams
intact because they have no established logger timeline.

This is the raw-reader boundary for one-node recording (#169). Source/model
applicability, explicit epoch reconstruction, bounded clock composition,
inter-node alignment and higher-level IMU analysis remain separate work.
Host decoding does not qualify physical timing or FIFO/capture association.

Validation: `python -m pytest analysis/tests/test_io_bdq_can_imu.py
analysis/tests/test_io_bdq_v2.py analysis/tests/test_io_bdq.py
analysis/tests/test_io_bdq_storage_types.py -q` with `analysis` on `PYTHONPATH`.
The CAN reader tests use independently written literal sample/evidence bytes,
including signed axes, complete snapshot flags, explicit segment restarts,
known versus unknown zero losses, reserved bytes and split 64-bit values.
Artifact round trips preserve raw numeric evidence and catalog provenance.

`python firmware/tools/test_remote_imu_recording_runtime.py --compiler g++`
compiles the production remote-stream, catalog and writer sources, writes a
complete host fixture BDQ and independently verifies it through the Python
reader and literal expected bytes. Pass `--output path.bdq` to retain the file.
The test checks catalog identities, axes, segment/model/boundary fields, snapshot
bit 8, reception ordinals above 32 bits, evidence-before-data order and truncated
evidence recovery. It exercises the storage boundary without claiming a device
or physical timing result.
