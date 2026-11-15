# r28: bounded logger sample-buffer trial

Logger base d9fc96c8dc0fb7e067d48b5fb1b7d3215bab1951 (r26); retain master
d1e3b6ba5f3f81c2e77c3236b741f2d7757abdd0 (r27 late diagnostics), existing nodes,
card, configuration, ADC-off workload and six-minute normal recording procedure.

Only selected environment bodaqs_s3_mini_n4r2_imu_sample_buffer512 sets the
new compile-time BODAQS_LOGGER_SAMPLE_QUEUE_CAPACITY=512 override. It is restricted
to the512-byte, four-node bench. Existing environments keep their canonical
geometry-derived queue sizes. No config field, public function signature, wire
geometry, master ingress, transport window, ACK rule, storage output buffer,
priority, pacing or file format changes. Evidence queues remain512 entries.

Each logger sample queue grows128 to512 records of516bytes. Additional payload
allocation is198144bytes/node,792576bytes for four nodes. Four stream dynamic
reservations rise750080 to1542656bytes, including unchanged evidence/provenance/
model/anchor allocations. The r27 footer charged1111450bytes including storage;
with the sole capacity change, the expected aggregate is1904026bytes. This is
193126bytes below nominal2MiB PSRAM if conservatively charging the entire total
there, although some charged state is internal/static and other application
allocations also exist. The prior pre-start largest block was2031604bytes.
These calculations support a bounded trial, not guaranteed available runtime RAM.

The same private capacity feeds allocation and allocatedBufferBytes(), so the
existing admission report includes the extra memory. Existing PSRAM-preferred
allocation with its current fallback is unchanged. Every participant allocates
before PREPARE/START; any failure releases all attempted allocations and prevents
remote authorization. No allocations occur in the sample path. Verify actual
four-source admission, queue capacities and charged bytes in the physical run.

At full35-reading packets and3333readings/s, capacity corresponds approximately
to1.34s versus5.38s per node. Partial packets reduce that duration. Existing queue
ownership, atomic indices, full->Blocked, duplicate recognition, retry semantics,
FIFO bytes, retirement/release barriers and integrity checks remain unchanged.
Buffer custody remains distinct from SD durability; ACK meaning is unchanged.

Prediction: if storage bursts cause the upstream choke, the same normal slow
writes should produce larger but non-full queues, fewer consumer waits/held
windows and fewer source gaps. Delivery and late sample replies should improve.
If queues still fill or quiet throughput declines despite their remaining below
capacity, extra buffering is insufficient; do not call this a wire-capacity gain.
Inspect all four source boundaries, integrity, storage errors and allocation
results. No artificial stall, forced drop or admission-policy relaxation.

Offline evidence: real four-stream128/512 capacity, full/duplicate/retry,
drain/refill across ring wrap, exact payload bytes, reservation delta, allocation
failure cleanup and reset; full default host suite; selected four-source
integrated512/timeline/ordinary-fetch20 run; selected ESP32-S3 build and recipe
flag audit. The target trial remains physical qualification debt.
