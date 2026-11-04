#include "bodaqs_control_acquisition.h"
#include "bodaqs_control_snapshot.h"
#include "bodaqs_master_service.h"
#include <cassert>
#include <cstdio>
#include <cstring>
struct Hardware
{
    BodaqsAcquisitionEvent event = {};
    uint32_t generation = 0;
    uint8_t command = 0;
    static void drive(void *p, uint8_t action, uint32_t generation, uint64_t, uint32_t,
                      BodaqsAcquisitionEvent *out)
    {
        auto &h = *static_cast<Hardware *>(p);
        if (action)
        {
            h.command = action;
            h.generation = generation;
        }
        *out = h.event;
        h.event = {};
    }
    void emit(uint8_t kind, bool proof = false, bool empty = false, uint32_t sequence = 0,
              uint8_t stream = 1)
    {
        event = {};
        event.generation = generation;
        event.kind = kind;
        event.register_proof_current = proof;
        event.known_empty = empty;
        event.node_clock_epoch = 1;
        event.sensor_clock_epoch = 2;
        if (kind == BODAQS_ACQ_FIRST || (kind == BODAQS_ACQ_STOPPED && !empty))
        {
            bodaqs_control_put_u32(event.boundary, sequence);
            bodaqs_control_put_u32(event.boundary + 4, 4321);
            event.boundary[8] = stream;
            event.boundary[9] = 7;
        }
    }
};
struct Rig
{
    BodaqsControlNode node = {};
    BodaqsControlAuthority authority = {};
    BodaqsControlAcquisition acq = {};
    BodaqsControlSnapshot snapshot = {};
    BodaqsMasterService master = {};
    Hardware hardware;
    uint8_t effective[192] = {};
    uint32_t now = 1000, object[2] = {}, query = 100;
    uint64_t snapshotId = 0;
    Rig(bool supported = true)
    {
        node.boot_id = 9;
        node.active_session = 11;
        node.endpoint_mask = 1;
        node.endpoint_epoch[0] = 2;
        authority.high_water = 1;
        authority.next_challenge = 12345;
        effective[4] = 2;
        bodaqs_control_put_u64(effective + 32, 7);
        effective[20] = 3;
        bodaqs_control_acquisition_init(&acq, &authority, &node, effective,
                                        supported ? Hardware::drive : nullptr, &hardware);
        snapshot.capture_acquisition = bodaqs_control_acquisition_capture;
        snapshot.acquisition_context = &acq;
        BodaqsMasterIdentity identity = {};
        bodaqs_master_service_init(&master, &identity);
        bodaqs_control_exchange_init(&master.control, 99);
        master.measurement.mode.phase = 2;
        master.measurement.mode.context = 10;
        master.measurement.mode.session = 11;
        master.measurement.mode.recording = 13;
        master.discovery[0].flags = 1;
        master.discovery[0].boot_id = 9;
    }
    BodaqsControlRecord request(uint8_t opcode, uint32_t operation = 0)
    {
        BodaqsControlRecord q = {};
        q.opcode = opcode;
        q.operation = operation ? operation : ++query;
        q.endpoint = 255;
        q.node_boot_id = 9;
        q.session = 11;
        return q;
    }
    BodaqsControlRecord send(BodaqsControlRecord q)
    {
        bool protectedLane = q.opcode >= 0x25 && q.opcode <= 0x27;
        uint8_t cls = protectedLane ? 4 : 3;
        unsigned lane = protectedLane ? 1 : 0;
        if (!protectedLane)
            now += 250;
        assert(bodaqs_control_request_valid(&q));
        BodaqsControlWrapped wrapped = {};
        wrapped.master_boot_id = 99;
        wrapped.node_address = 0;
        wrapped.record = q;
        uint8_t bytes[68] = {}, wire[64], answer[84];
        BodaqsFragmentState tx = {};
        assert(bodaqs_control_encode_wrapped(&wrapped, bytes));
        assert(bodaqs_fragment_seal(&tx, bytes, 68, 10, ++object[lane], 0, cls, 0, 64));
        for (unsigned i = 0; i < 2; i++)
        {
            BodaqsMeasurementSlot part = {};
            assert(bodaqs_fragment_emit(&tx, bytes, (uint8_t)i, &part));
            assert(bodaqs_measurement_encode(&part, wire, 64));
            assert(bodaqs_master_service_process_transfer(&master, wire, 64, now, answer) == 0);
        }
        uint8_t address, can[64];
        uint16_t transaction, decoded;
        if (bodaqs_master_service_control_transmit(&master, now, &address, &transaction, can))
        {
            BodaqsControlRecord incoming = {}, reply = {}, decodedReply = {};
            assert(address == 0 && bodaqs_control_decode_can(can, 64, false, &decoded, &incoming));
            assert(bodaqs_control_authority_process(&authority, &node, &incoming, now, nullptr,
                                                    nullptr, &reply) ||
                   bodaqs_control_acquisition_process(&acq, &incoming, now, &reply) ||
                   bodaqs_control_snapshot_process(&snapshot, &node, &incoming, now, &reply));
            assert(bodaqs_control_encode_can(&reply, true, transaction, can));
            assert(bodaqs_control_decode_can(can, 64, true, &decoded, &decodedReply));
            assert(bodaqs_master_service_control_receive(&master, 0, decoded, &decodedReply));
        }
        BodaqsFragmentState rx = {};
        uint8_t accepted[68] = {};
        BodaqsMeasurementSlot ack = {};
        for (unsigned i = 0; i < 2; i++)
        {
            BodaqsMeasurementSlot poll = {};
            poll.kind = 1;
            poll.context = 10;
            poll.node = 0;
            poll.body[0] = cls;
            poll.index = (uint8_t)i;
            if (i)
                poll.object = rx.object;
            assert(bodaqs_measurement_encode(&poll, wire, 64));
            assert(bodaqs_master_service_process_transfer(&master, wire, 64, now, answer) == 0);
            BodaqsMeasurementSlot part = {};
            assert(bodaqs_measurement_decode(answer, 64, &part));
            assert(bodaqs_fragment_accept(&rx, accepted, 68, &part, 1, &ack) == (i ? 1 : 0));
        }
        assert(bodaqs_measurement_encode(&ack, wire, 64));
        assert(bodaqs_master_service_process_transfer(&master, wire, 64, now, answer) == 0);
        assert(bodaqs_control_decode_wrapped(accepted, 64, &wrapped));
        return wrapped.record;
    }
    BodaqsControlRecord begin()
    {
        auto q = request(0x20, 2);
        q.transfer = 12;
        q.data_length = 24;
        q.data[0] = 4;
        q.data[2] = 1;
        q.data[4] = 112;
        q.data[6] = 1;
        q.data[8] = 13;
        return q;
    }
    void stage()
    {
        auto q = begin();
        assert(send(q).data[0] == 2);
        uint8_t staged[112] = {};
        memcpy(staged, q.data, 16);
        bodaqs_control_put_u64(staged + 16, 7);
        bodaqs_control_put_u64(staged + 64, 2);
        // Initial challenge is unavailable before all immutable pages exist.
        auto challenge = request(0x26);
        challenge.transfer = 12;
        challenge.data_length = 16;
        challenge.data[0] = 13;
        challenge.data[8] = 1;
        challenge.data[13] = 1;
        assert(send(challenge).data[1] == 11);
        for (unsigned i = 0; i < 5; i++)
        {
            auto page = request(0x21, 2);
            page.transfer = 12;
            page.page = (uint8_t)i;
            page.data_length = i == 4 ? 16 : 24;
            memcpy(page.data, staged + 24 * i, page.data_length);
            assert(send(page).data[0] == 2);
        }
    }
    void prepare()
    {
        stage();
        auto challenge = request(0x26);
        challenge.transfer = 12;
        challenge.data_length = 16;
        challenge.data[0] = 13;
        challenge.data[8] = 1;
        challenge.data[13] = 1;
        auto answer = send(challenge);
        assert(answer.opcode == 0x26);
        assert(bodaqs_control_get_u32(answer.data + 8) == now * 1000U);
        assert((uint32_t)(bodaqs_control_get_u32(answer.data + 16) -
                          bodaqs_control_get_u32(answer.data + 8)) == 1000000U);
        auto retry = send(challenge);
        assert(!memcmp(answer.data, retry.data, 24));
        auto commit = request(0x22, 2);
        commit.transfer = 12;
        commit.data_length = 24;
        commit.data[0] = 13;
        memcpy(commit.data + 8, answer.data, 8);
        commit.data[16] = 1;
        assert(send(commit).data[0] == 2);
        bodaqs_control_acquisition_tick(&acq, now);
        assert(hardware.command == BODAQS_ACQ_PREPARE);
    }
    void renew(uint32_t sequence)
    {
        auto q = request(0x26);
        q.data_length = 16;
        q.data[0] = 13;
        q.data[12] = 1;
        q.data[13] = 1;
        bodaqs_control_put_u32(q.data + 8, sequence);
        auto answer = send(q);
        assert(answer.opcode == 0x26);
        auto proof = request(0x27);
        proof.data_length = 24;
        proof.data[0] = 13;
        memcpy(proof.data + 8, answer.data, 8);
        bodaqs_control_put_u32(proof.data + 16, sequence);
        const auto epoch = node.endpoint_epoch[0];
        const auto high = authority.high_water;
        auto response = send(proof);
        assert(response.opcode == 0x27);
        assert(authority.high_water == high && node.endpoint_epoch[0] == epoch);
        auto duplicate = send(proof);
        assert(!memcmp(response.data, duplicate.data, 24));
    }
    void state(uint8_t bytes[128])
    {
        auto open = request(0x28);
        open.data_length = 8;
        auto metadata = send(open);
        assert(metadata.opcode == 0x28);
        snapshotId = metadata.transfer;
        for (unsigned i = 0; i < 6; i++)
        {
            auto page = request(7, open.operation);
            page.transfer = snapshotId;
            page.page = (uint8_t)i;
            auto value = send(page);
            memcpy(bytes + 24 * i, value.data, i == 5 ? 8 : 24);
        }
        auto release = request(8, open.operation);
        release.transfer = snapshotId;
        assert(send(release).opcode == 8);
        assert(bodaqs_control_descriptor_valid(bytes, 128, 5, 255));
    }
};
int main()
{
    Rig unsupported(false);
    auto rejected = unsupported.send(unsupported.begin());
    assert(rejected.opcode == 127 && rejected.data[1] == 27);
    Rig rig;
    rig.prepare();
    bodaqs_master_service_measurement_fence(&rig.master, true, true);
    assert(!rig.master.measurement.quiescent && !rig.master.measurement.fenced);

    // Independent preparation hardware has not completed; protected renewal remains serviceable.
    rig.now += 100;
    rig.renew(2);
    assert(rig.acq.phase == 1 && rig.node.pending_operation == 2);
    rig.hardware.emit(BODAQS_ACQ_READY, true);
    bodaqs_control_acquisition_tick(&rig.acq, rig.now);
    assert(rig.acq.phase == 2 && rig.node.pending_operation == 0);
    assert(bodaqs_control_get_u64(rig.effective + 32) == 7); // runtime never edits applied revision
    auto start = rig.request(0x24, 3);
    start.data_length = 24;
    start.data[0] = 13;
    bodaqs_control_put_u64(start.data + 8, rig.node.endpoint_epoch[0]);
    bodaqs_control_put_u64(start.data + 16, 7);
    assert(rig.send(start).data[0] == 2);
    bodaqs_control_acquisition_tick(&rig.acq, rig.now);
    assert(rig.acq.phase == 2 && rig.node.pending_operation == 3); // no receipt-derived boundary
    rig.hardware.emit(BODAQS_ACQ_FIRST, false, false);
    bodaqs_control_acquisition_tick(&rig.acq, rig.now);
    assert(rig.acq.phase == 3 && rig.acq.first_valid && !rig.acq.known_empty);
    auto stop = rig.request(0x25, 4);
    stop.data_length = 24;
    stop.data[0] = 13;
    assert(rig.send(stop).data[0] == 2);
    bodaqs_control_acquisition_tick(&rig.acq, rig.now);
    auto forbidden = rig.request(0x26);
    forbidden.data_length = 16;
    forbidden.data[0] = 13;
    forbidden.data[8] = 3;
    forbidden.data[12] = 1;
    forbidden.data[13] = 1;
    assert(rig.send(forbidden).data[1] == 30);
    rig.hardware.emit(BODAQS_ACQ_STOPPED, true, false, 17);
    bodaqs_control_acquisition_tick(&rig.acq, rig.now);
    assert(rig.acq.phase == 5 && rig.acq.final_valid && !rig.acq.lease_valid);
    auto release = rig.request(0x29, 5);
    release.data_length = 24;
    release.data[0] = 13;
    assert(rig.send(release).data[1] == 33); // explicit fence before release
    auto fence = rig.request(0x2A, 5);
    fence.data_length = 24;
    fence.data[0] = 13;
    assert(rig.send(fence).data[0] == 2);
    bodaqs_control_acquisition_tick(&rig.acq, rig.now);
    rig.hardware.emit(BODAQS_ACQ_FENCED);
    bodaqs_control_acquisition_tick(&rig.acq, rig.now);
    auto operation = rig.request(0x14);
    operation.data_length = 4;
    operation.data[0] = 5;
    assert(rig.send(operation).data[0] == 3);
    assert(rig.master.acquisition_retirement_pending && !rig.master.measurement.fenced);
    assert(rig.master.acquisition_retirement_generation == 1);
    bodaqs_master_service_measurement_fence(&rig.master, true, false);
    assert(!rig.master.measurement.fenced);
    bodaqs_master_service_measurement_fence(&rig.master, true, true);
    assert(rig.master.measurement.fenced);
    uint8_t state[128];
    rig.state(state);
    assert(state[6] == 5 && state[88 + 9] == 7 && bodaqs_control_get_u32(state + 104) == 17);
    release.operation = 6;
    assert(rig.send(release).data[0] == 3);
    assert(!rig.acq.recording);
    // STOP supersedes pending PREPARE; delayed READY cannot undo terminality/high-water.
    Rig canceled;
    canceled.prepare();
    auto pendingGeneration = canceled.hardware.generation;
    stop = canceled.request(0x25, 3);
    stop.data_length = 24;
    stop.data[0] = 13;
    assert(canceled.send(stop).data[0] == 2);
    bodaqs_control_acquisition_tick(&canceled.acq, canceled.now);
    canceled.hardware.emit(BODAQS_ACQ_READY, true);
    canceled.hardware.event.generation = pendingGeneration;
    bodaqs_control_acquisition_tick(&canceled.acq, canceled.now);
    assert(canceled.acq.phase == 4 && canceled.authority.high_water == 3);
    canceled.hardware.emit(BODAQS_ACQ_STOPPED, true, true);
    bodaqs_control_acquisition_tick(&canceled.acq, canceled.now);
    assert(canceled.acq.known_empty && !canceled.acq.first_valid && !canceled.acq.final_valid);
    // Expiry is driven without requests, and unknown final is distinct from known-empty.
    Rig expired;
    expired.prepare();
    expired.now = expired.acq.lease_deadline;
    bodaqs_control_acquisition_tick(&expired.acq, expired.now);
    assert(expired.acq.terminal && expired.acq.reason == 29);
    expired.hardware.emit(BODAQS_ACQ_STOPPED, true, false);
    expired.hardware.event.boundary[9] = 0;
    bodaqs_control_acquisition_tick(&expired.acq, expired.now);
    assert(!expired.acq.known_empty && !expired.acq.final_valid);
    // Five-second readiness starts at accepted COMMIT, while leases renew independently.
    Rig notReady;
    notReady.prepare();
    const auto accepted = notReady.acq.prepared_ms;
    for (unsigned sequence = 2; sequence <= 50; ++sequence)
    {
        notReady.now = accepted + (sequence - 1) * 100U;
        notReady.renew(sequence);
    }
    notReady.now = accepted + 5000U;
    bodaqs_control_acquisition_tick(&notReady.acq, notReady.now);
    assert(notReady.acq.terminal && notReady.acq.reason == 18 && !notReady.acq.ready);
    Rig stageExpired;
    assert(stageExpired.send(stageExpired.begin()).data[0] == 2);
    stageExpired.now += 5000U;
    bodaqs_control_acquisition_tick(&stageExpired.acq, stageExpired.now);
    assert(!stageExpired.acq.staging && !stageExpired.node.pending_operation &&
           !stageExpired.acq.recording);
    Rig aborted;
    assert(aborted.send(aborted.begin()).data[0] == 2);
    auto abort = aborted.request(0x23, 2);
    abort.transfer = 12;
    assert(aborted.send(abort).data[0] == 3);
    assert(aborted.send(abort).data[0] == 3 && !aborted.acq.recording);
    // Protected STOP may overtake a COMMIT still queued in the ordinary lane.
    Rig overtaken;
    overtaken.stage();
    auto stagedChallenge = overtaken.request(0x26);
    stagedChallenge.transfer = 12;
    stagedChallenge.data_length = 16;
    stagedChallenge.data[0] = 13;
    stagedChallenge.data[8] = 1;
    stagedChallenge.data[13] = 1;
    auto stagedProof = overtaken.send(stagedChallenge);
    auto cancelStage = overtaken.request(0x25, 3);
    cancelStage.data_length = 24;
    cancelStage.data[0] = 13;
    assert(overtaken.send(cancelStage).data[0] == 3);
    auto lateCommit = overtaken.request(0x22, 2);
    lateCommit.transfer = 12;
    lateCommit.data_length = 24;
    lateCommit.data[0] = 13;
    lateCommit.data[16] = 1;
    memcpy(lateCommit.data + 8, stagedProof.data, 8);
    auto lateOutcome = overtaken.send(lateCommit);
    assert(lateOutcome.data[0] == 6 && !overtaken.acq.recording && overtaken.hardware.command == 0);
    // Native capture adapter preserves phase, deadlines and explicit clock epoch.
    Rig native;
    auto nativeClock = [](void *p, uint32_t *epoch) -> uint32_t
    {
        *epoch = 23;
        return *static_cast<uint32_t *>(p) * 1000U + 321U;
    };
    assert(bodaqs_control_acquisition_set_clock(&native.acq, nativeClock, &native.now));
    native.stage();
    auto nativeChallenge = native.request(0x26);
    nativeChallenge.transfer = 12;
    nativeChallenge.data_length = 16;
    nativeChallenge.data[0] = 13;
    nativeChallenge.data[8] = 1;
    nativeChallenge.data[13] = 1;
    auto nativeReply = native.send(nativeChallenge);
    assert(bodaqs_control_get_u32(nativeReply.data + 8) == native.now * 1000U + 321U);
    assert(bodaqs_control_get_u32(nativeReply.data + 12) == native.now * 1000U + 300321U);
    assert(native.acq.node_clock_epoch == 23);
    // Initial proof freshness is issuance-based, never COMMIT receipt-based.
    Rig delayed;
    delayed.stage();
    auto challenge = delayed.request(0x26);
    challenge.transfer = 12;
    challenge.data_length = 16;
    challenge.data[0] = 13;
    challenge.data[8] = 1;
    challenge.data[13] = 1;
    auto challengeReply = delayed.send(challenge);
    auto commit = delayed.request(0x22, 2);
    commit.transfer = 12;
    commit.data_length = 24;
    commit.data[0] = 13;
    commit.data[16] = 1;
    memcpy(commit.data + 8, challengeReply.data, 8);
    delayed.now += 51;
    assert(delayed.send(commit).data[1] == 20 && !delayed.acq.recording);
    // Acquisition state shares one immutable pin with endpoint descriptors.
    auto open = canceled.request(0x28);
    open.data_length = 8;
    auto opened = canceled.send(open);
    const auto capturedEpoch = canceled.node.endpoint_epoch[0];
    canceled.node.endpoint_epoch[0] += 7;
    auto changed = open;
    changed.data[0] = 99;
    rejected = {};
    assert(bodaqs_control_snapshot_process(&canceled.snapshot, &canceled.node, &changed,
                                           canceled.now, &rejected));
    assert(rejected.opcode == 127 && rejected.data[1] == 12);
    auto page = canceled.request(7, open.operation);
    page.transfer = opened.transfer;
    page.page = 2;
    auto immutable = canceled.send(page);
    assert(bodaqs_control_get_u64(immutable.data + 16) == capturedEpoch);
    // A freshly bound authority can clean an abandoned stopped membership.
    BodaqsControlRecord bindChallenge = canceled.request(1), bindReply = {};
    bindChallenge.data_length = 8;
    bodaqs_control_put_u64(bindChallenge.data, 22);
    auto entropy = [](void *) -> uint64_t { return 8675309; };
    assert(bodaqs_control_authority_process(&canceled.authority, &canceled.node, &bindChallenge,
                                            canceled.now, entropy, nullptr, &bindReply));
    auto bind = canceled.request(2, 1);
    bind.session = 22;
    bind.transfer = bindReply.transfer;
    assert(bodaqs_control_authority_process(&canceled.authority, &canceled.node, &bind,
                                            canceled.now, entropy, nullptr, &bindReply));
    assert(bindReply.opcode == 2 && canceled.acq.recording == 13 && canceled.acq.owner == 11);
    // Empty reboot cleanup still requires a physical fence. Its terminal ID
    // is scoped to the bound session, so a later owner may reuse the number.
    Rig empty;
    uint64_t entropyWord=100;
    auto nextEntropy=[](void* p)->uint64_t {return ++*static_cast<uint64_t*>(p);};
    auto bindOwner=[&](uint64_t session) {
        auto challenge=empty.request(1);challenge.data_length=8;challenge.session=0;
        bodaqs_control_put_u64(challenge.data,session);
        BodaqsControlRecord reply={};
        assert(bodaqs_control_authority_process(&empty.authority,&empty.node,&challenge,
            empty.now,nextEntropy,&entropyWord,&reply));
        auto bind=empty.request(2,1);bind.session=session;bind.transfer=reply.transfer;
        assert(bodaqs_control_authority_process(&empty.authority,&empty.node,&bind,
            empty.now,nextEntropy,&entropyWord,&reply));
        assert(reply.opcode==2 && reply.data[0]==0);
    };
    bindOwner(22);
    auto cleanupFence=empty.request(0x2A,2);cleanupFence.session=22;cleanupFence.data_length=24;
    bodaqs_control_put_u64(cleanupFence.data,71);
    BodaqsControlRecord cleanupResult={};
    assert(bodaqs_control_acquisition_process(&empty.acq,&cleanupFence,empty.now,&cleanupResult));
    assert(cleanupResult.data[0]==2 && !empty.acq.fenced && !empty.acq.recording);
    bodaqs_control_acquisition_tick(&empty.acq,++empty.now);
    assert(!empty.acq.fenced);
    empty.hardware.emit(BODAQS_ACQ_FENCED);
    bodaqs_control_acquisition_tick(&empty.acq,++empty.now);
    assert(empty.acq.fenced && !empty.acq.recording);
    auto cleanupRelease=cleanupFence;cleanupRelease.opcode=0x29;cleanupRelease.operation=3;
    assert(bodaqs_control_acquisition_process(&empty.acq,&cleanupRelease,empty.now,&cleanupResult));
    assert(cleanupResult.data[0]==3 && !empty.acq.recording);
    bindOwner(33);
    auto reused=empty.begin();reused.session=33;bodaqs_control_put_u64(reused.data+8,71);
    assert(bodaqs_control_acquisition_process(&empty.acq,&reused,empty.now,&cleanupResult));
    assert(cleanupResult.data[0]==2 && empty.acq.staging && !empty.acq.lease_valid);
    auto stale=cleanupRelease;stale.operation=4;
    assert(bodaqs_control_acquisition_process(&empty.acq,&stale,empty.now,&cleanupResult));
    assert(cleanupResult.opcode==127 && cleanupResult.data[1]==5 && empty.acq.staging);
    puts("real fragmented master/CAN acquisition lifecycle tests passed");
}
