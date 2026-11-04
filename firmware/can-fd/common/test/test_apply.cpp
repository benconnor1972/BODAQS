#include "CanMasterProtocol.h"
#include "bodaqs_control_apply.h"
#include "bodaqs_control_apply_client.h"
#include "bodaqs_control_observer.h"
#include "bodaqs_master_service.h"
#include <cassert>
#include <cstdio>
#include <cstring>
static int reg(void *, bool, uint8_t, uint8_t *, uint32_t)
{
    return 0;
}
void stagingExpiry()
{
    BodaqsControlNode view = {};
    view.boot_id = 7;
    view.endpoint_mask = 1;
    view.active_session = 9;
    view.endpoint_epoch[0] = 2;
    view.flags = 1;
    BodaqsControlAuthority authority = {};
    authority.high_water = 1;
    BodaqsImuDisabled backend;
    bodaqs_imu_disabled_init(&backend, reg, nullptr, nullptr);
    BodaqsControlApply apply;
    bodaqs_control_apply_init(&apply, &authority, &view, &backend);
    BodaqsControlRecord begin = {}, reply;
    begin.opcode = 0x10;
    begin.operation = 2;
    begin.node_boot_id = 7;
    begin.session = 9;
    begin.transfer = 11;
    begin.data_length = 24;
    const uint8_t metadata[24] = {1, 0, 1, 0, 44, 0, 0, 0, 1, 0, 0, 0,
                                  0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0};
    memcpy(begin.data, metadata, 24);
    assert(bodaqs_control_apply_process(&apply, &begin, 100, &reply));
    assert(reply.data[0] == 2 && view.pending_operation == 2 && authority.high_water == 2);
    BodaqsControlRecord query = begin;
    query.opcode = 0x14;
    query.operation = 23;
    query.transfer = 0;
    query.data_length = 4;
    memset(query.data, 0, 24);
    query.data[0] = 2;
    assert(
        bodaqs_control_authority_process(&authority, &view, &query, 101, nullptr, nullptr, &reply));
    assert(reply.data[0] == 2 && reply.data[3] == 0x14);
    bodaqs_control_apply_tick(&apply, 5100);
    assert(!view.pending_operation && !(view.flags & 0x30));
    assert(bodaqs_control_apply_process(&apply, &begin, 5101, &reply));
    assert(reply.data[0] == 5 && reply.data[1] == 10);
}

struct Registers
{
    uint8_t bytes[3][128] = {};
    uint8_t bank = 0;
    unsigned resets = 0, reads = 0, writes = 0;
    bool stuck_reset = false, spi_failure = false;
    uint8_t ignore_write = 0;
    Registers()
    {
        reset();
    }
    void reset()
    {
        memset(bytes, 0, sizeof(bytes));
        bytes[0][15] = 0x6c;
        bytes[0][18] = 4;
        bytes[0][24] = 0xe0;
        bank = 0;
    }
    static int io(void *ctx, bool write, uint8_t address, uint8_t *value, uint32_t)
    {
        auto &s = *static_cast<Registers *>(ctx);
        if (s.spi_failure)
            return -1;
        if (write)
        {
            ++s.writes;
            if (address == 1 && s.ignore_write != 1)
            {
                s.bank = (*value & 0x80) ? 1 : ((*value & 0x40) ? 2 : 0);
                s.bytes[0][1] = *value;
            }
            else if (s.bank == 0 && address == 18 && (*value & 1))
            {
                ++s.resets;
                s.reset();
                if (s.stuck_reset)
                    s.bytes[0][18] = 5;
            }
            else if (address != s.ignore_write)
                s.bytes[s.bank][address] = *value;
        }
        else
        {
            ++s.reads;
            *value = address == 1 ? s.bytes[0][1] : s.bytes[s.bank][address];
        }
        return 1;
    }
};
struct Fixture
{
    BodaqsControlNode view = {};
    BodaqsControlAuthority authority = {};
    Registers regs;
    BodaqsImuDisabled backend;
    BodaqsControlApply apply;
    uint32_t now = 100;
    BodaqsControlRecord begin = {}, reply = {};
    Fixture()
    {
        view.boot_id = 7;
        view.endpoint_mask = 1;
        view.active_session = 9;
        view.endpoint_epoch[0] = 2;
        view.flags = 1;
        authority.high_water = 1;
        bodaqs_imu_disabled_init(&backend, Registers::io, nullptr, &regs);
        bodaqs_control_apply_init(&apply, &authority, &view, &backend);
    }
    void open(uint32_t sequence = 2, uint64_t revision = 0, uint64_t generation = 1)
    {
        begin = {};
        begin.opcode = 0x10;
        begin.operation = sequence;
        begin.node_boot_id = 7;
        begin.session = 9;
        begin.transfer = sequence + 10;
        begin.data_length = 24;
        const uint8_t metadata[24] = {1, 0, 1, 0, 44, 0, 0, 0, 1, 0, 0, 0,
                                      0, 0, 0, 0, 0,  0, 0, 0, 0, 0, 0, 0};
        memcpy(begin.data, metadata, 24);
        bodaqs_control_put_u64(begin.data + 8, generation);
        bodaqs_control_put_u64(begin.data + 16, revision);
        send(begin);
        assert(reply.data[0] == 2);
    }
    void send(const BodaqsControlRecord &q)
    {
        assert(bodaqs_control_apply_process(&apply, &q, now, &reply));
    }
    void page(unsigned n)
    {
        auto q = begin;
        q.opcode = 0x11;
        q.page = n;
        q.data_length = n ? 20 : 24;
        memset(q.data, 0, 24);
        if (!n)
        {
            q.data[0] = 1;
            q.data[2] = 1;
        }
        send(q);
    }
    void commit()
    {
        auto q = begin;
        q.opcode = 0x12;
        send(q);
    }
    void finish()
    {
        for (unsigned i = 0; i < 2100 && view.pending_operation; ++i)
            bodaqs_control_apply_tick(&apply, ++now);
    }
    void descriptor(uint8_t *d)
    {
        bodaqs_control_apply_capture(&apply, &view, 0, true, d);
        assert(bodaqs_control_descriptor_valid(d, 192, 3, 0));
    }
};
void physicalDisableAndFreshNoOp()
{
    Fixture f;
    f.open();
    f.page(0);
    f.page(1);
    assert(f.regs.writes == 0);
    f.commit();
    assert(f.reply.data[0] == 2 && (f.view.flags & 16));
    auto abort = f.begin;
    abort.opcode = 0x13;
    abort.data_length = 0;
    memset(abort.data, 0, 24);
    f.send(abort);
    assert(f.reply.data[0] == 1 && f.view.pending_operation == 2);
    f.finish();
    uint8_t d[192];
    f.descriptor(d);
    assert(d[4] == 1 && d[5] == 0 && d[6] == 0 && bodaqs_control_get_u32(d + 8) == 0x441);
    assert(bodaqs_control_get_u64(d + 32) == 1 && bodaqs_control_get_u64(d + 24) == 1 &&
           bodaqs_control_get_u64(d + 144) == 9);
    // Independent wire-contract register image literal: 07h-19h,01h,5Eh,5Fh.
    const uint8_t image[24] = {0,  0, 0, 0, 0, 0,    0, 0, 0x6c, 4, 12, 0x44,
                               12, 0, 0, 0, 0, 0xe2, 0, 0, 0,    0, 0,  0};
    assert(!memcmp(d + 152, image, 24));
    assert(f.regs.resets == 1);
    const auto epoch = f.view.endpoint_epoch[0];
    const auto reads = f.regs.reads;
    f.commit();
    assert(f.reply.data[0] == 3 &&
           f.regs.reads == reads); // stale expected revision is a cached retry
    f.open(3, 1);
    f.page(0);
    f.page(1);
    f.commit();
    f.finish();
    f.descriptor(d);
    assert(f.regs.resets == 1 && f.regs.reads > reads && bodaqs_control_get_u64(d + 32) == 1);
    assert(f.view.endpoint_epoch[0] == epoch); // repeated verification alone does not change epoch
    f.open(4, 1, 2);
    f.page(0);
    f.page(1);
    f.commit();
    f.finish();
    f.descriptor(d);
    assert(bodaqs_control_get_u64(d + 24) == 2 && bodaqs_control_get_u64(d + 32) == 1);
    assert(f.view.endpoint_epoch[0] == epoch + 1);
}

void invalidStagingNeverTouchesHardware()
{
    Fixture incomplete;
    incomplete.open();
    incomplete.page(0);
    incomplete.commit();
    assert(incomplete.reply.data[0] == 5 && incomplete.reply.data[1] == 11 &&
           !incomplete.regs.writes);
    incomplete.page(1);
    assert(incomplete.reply.data[0] == 5 && !incomplete.view.pending_operation);
    Fixture conflict;
    conflict.open();
    conflict.page(0);
    auto q = conflict.begin;
    q.opcode = 0x11;
    memset(q.data, 0, 24);
    q.data[0] = 1;
    q.data[2] = 1;
    q.data[4] = 1;
    conflict.send(q);
    assert(conflict.reply.data[1] == 12 && !conflict.view.pending_operation);
    conflict.commit();
    assert(conflict.reply.data[0] == 5 && conflict.reply.data[1] == 9 && !conflict.regs.writes);
    Fixture abort;
    abort.open();
    q = abort.begin;
    q.opcode = 0x13;
    q.data_length = 0;
    memset(q.data, 0, 24);
    abort.send(q);
    assert(abort.reply.data[0] == 0 && !abort.view.pending_operation && !abort.regs.writes);
    abort.send(q);
    assert(abort.reply.data[0] == 0); // lost abort acknowledgement is idempotent
    abort.commit();
    assert(abort.reply.data[0] == 5 && !abort.regs.writes);
    Fixture metadata;
    metadata.open();
    q = metadata.begin;
    q.opcode = 0x12;
    q.data[8] = 2;
    metadata.send(q);
    assert(metadata.reply.data[1] == 12 && metadata.view.pending_operation == 2 &&
           !metadata.regs.writes);
    metadata.page(0);
    metadata.page(1);
    metadata.view.flags |= 2;
    metadata.commit();
    assert(metadata.reply.data[0] == 5 && metadata.reply.data[1] == 8 && !metadata.regs.writes);
    Fixture unsupported;
    unsupported.open();
    q = unsupported.begin;
    q.opcode = 0x11;
    memset(q.data, 0, 24);
    q.data[0] = 1;
    q.data[2] = 1;
    q.data[4] = 1;
    q.data[8] = 1;
    q.data[10] = 1;
    unsupported.send(q);
    unsupported.page(1);
    unsupported.commit();
    assert(unsupported.reply.data[0] == 5 && unsupported.reply.data[1] == 3 &&
           !unsupported.regs.writes);
}
void faultsPreserveHistoricalEvidenceAndScope()
{
    Fixture f;
    f.open();
    f.page(0);
    f.page(1);
    f.commit();
    f.finish();
    const auto epoch = f.view.endpoint_epoch[0];
    const auto resets = f.regs.resets;
    auto stale = f.begin;
    stale.operation = 3;
    stale.transfer = 15;
    f.send(stale);
    assert(f.reply.data[0] == 1 && f.reply.data[1] == 6 && f.authority.high_water == 2);
    stale = f.begin;
    stale.session = 8;
    f.send(stale);
    assert(f.reply.data[1] == 5 && f.regs.resets == resets);
    stale = f.begin;
    stale.node_boot_id = 8;
    f.send(stale);
    assert(f.reply.data[1] == 4);
    f.regs.bytes[0][16] = 0x94;
    f.regs.ignore_write = 16;
    f.open(3, 1, 2);
    f.page(0);
    f.page(1);
    f.commit();
    f.finish();
    uint8_t d[192];
    f.descriptor(d);
    assert(d[4] == 3 && bodaqs_control_get_u32(d + 16) == 0x441);
    assert(bodaqs_control_get_u64(d + 32) == 1 && bodaqs_control_get_u64(d + 24) == 1);
    assert(d[176] == 16 && d[178] == 4 && d[179] == 0 && d[180] == 0xfe);
    assert(f.authority.latest_result.data[0] == 5 && f.authority.latest_result.data[1] == 17);
    assert(f.view.endpoint_epoch[0] > epoch && !(f.view.flags & 256) && (f.view.flags & 512));
    for (unsigned reason = 14; reason <= 16; ++reason)
    {
        Fixture bad;
        if (reason == 14)
            bad.regs.spi_failure = true;
        if (reason == 15)
            bad.regs.bytes[0][15] = 0;
        if (reason == 16)
            bad.regs.stuck_reset = true;
        bad.open();
        bad.page(0);
        bad.page(1);
        bad.commit();
        bad.finish();
        bad.descriptor(d);
        assert(bad.authority.latest_result.data[1] == reason && d[4] == 3 &&
               !bad.view.pending_operation);
    }
    Fixture timed;
    timed.open();
    timed.page(0);
    timed.page(1);
    timed.commit();
    bodaqs_control_apply_tick(&timed.apply, timed.now + 2000);
    assert(timed.authority.latest_result.data[1] == 18 && !timed.view.pending_operation);
}

CanMasterProtocol::Frame wire(BodaqsMasterService &master, uint8_t type,
                              const BodaqsControlWrapped &wrapped)
{
    CanMasterProtocol::Frame q, r;
    q.type = static_cast<CanMasterProtocol::MessageType>(type);
    q.sequence = 123;
    q.payloadLength = 64;
    assert(bodaqs_control_encode_wrapped(&wrapped, q.payload));
    uint8_t tx[84], rx[84];
    assert(CanMasterProtocol::encodeSlot(q, tx, 84));
    assert(bodaqs_master_service_process_slot(&master, tx, rx) == BODAQS_MASTER_SLOT_PROCESSED);
    assert(CanMasterProtocol::decodeSlot(rx, 84, r) == CanMasterProtocol::DecodeResult::Ok);
    return r;
}
void deliverCan(BodaqsMasterService &master, Fixture &f, BodaqsControlSnapshot &snapshot,
                bool drop = false)
{
    uint8_t a, bytes[64];
    uint16_t tx, decodedTx;
    BodaqsControlRecord q, r;
    if (!bodaqs_control_exchange_transmit(&master.control, f.now, &a, &tx, bytes))
        return;
    assert(a == 0 && bodaqs_control_decode_can(bytes, 64, false, &decodedTx, &q));
    assert(decodedTx == tx);
    assert(
        bodaqs_control_authority_process(&f.authority, &f.view, &q, f.now, nullptr, nullptr, &r) ||
        bodaqs_control_apply_process(&f.apply, &q, f.now, &r) ||
        bodaqs_control_snapshot_process(&snapshot, &f.view, &q, f.now, &r) ||
        bodaqs_control_node_process(&f.view, &q, &r));
    assert(bodaqs_control_encode_can(&r, true, tx, bytes));
    assert(bodaqs_control_decode_can(bytes, 64, true, &decodedTx, &r));
    if (!drop)
        assert(bodaqs_control_exchange_receive(&master.control, a, decodedTx, &r));
}
void loggerDisabledAcrossRealSpiCanApplyAndSnapshot()
{
    Fixture f;
    BodaqsMasterService master;
    bodaqs_master_service_init(&master, nullptr);
    bodaqs_control_exchange_init(&master.control, 99);
    BodaqsControlSnapshot snapshot = {};
    snapshot.capture = bodaqs_control_apply_capture;
    snapshot.capture_context = &f.apply;
    BodaqsControlAuthorityClient authority;
    bodaqs_control_authority_client_init(&authority, 9);
    bodaqs_control_authority_client_node(&authority, 0, 7, true);
    authority.nodes[0].bound = true;
    authority.nodes[0].next_mutation = 2;
    BodaqsControlApplyClient client;
    bodaqs_control_apply_client_init(&client);
    const uint8_t disabled[44] = {1, 0, 1, 0};
    assert(bodaqs_control_apply_client_start(&client, &authority, 99, 0, 1, 0, disabled, f.now));
    bool lostCommit = false;
    for (unsigned i = 0; i < 4900 && client.phase; i++, f.now++)
    {
        bodaqs_control_apply_tick(&f.apply, f.now);
        BodaqsControlWrapped q, r;
        uint8_t type;
        if (!bodaqs_control_apply_client_next(&client, &authority, f.now, &q, &type))
            continue;
        auto response = wire(master, type, q);
        assert(bodaqs_control_decode_wrapped(response.payload, 64, &r));
        assert(bodaqs_control_apply_client_accept(&client, &authority,
                                                  static_cast<uint8_t>(response.type), &r, f.now));
        const bool drop = type == 6 && q.record.opcode == 0x12 && !lostCommit;
        deliverCan(master, f, snapshot, drop);
        lostCommit = lostCommit || drop;
    }
    assert(lostCommit && client.nodes[0].valid && client.nodes[0].kind == 3 &&
           client.nodes[0].revision == 1);
    assert(authority.nodes[0].next_mutation == 3 && f.regs.resets == 1);
    BodaqsControlObserver observer;
    bodaqs_control_observer_init(&observer);
    bodaqs_control_observer_boot(&observer, 99, 3);
    bodaqs_control_observer_node(&observer, 0, 7, 1, true);
    for (unsigned i = 0; i < 200 && !observer.nodes[0].endpoints[0].current; i++, f.now++)
    {
        BodaqsControlWrapped q, r;
        uint8_t type;
        bodaqs_control_observer_tick(&observer, f.now);
        assert(bodaqs_control_observer_next(&observer, &q, &type));
        auto response = wire(master, type, q);
        assert(bodaqs_control_decode_wrapped(response.payload, 64, &r));
        assert(bodaqs_control_observer_accept(&observer, static_cast<uint8_t>(response.type), &r,
                                              f.now));
        deliverCan(master, f, snapshot);
    }
    const auto &endpoint = observer.nodes[0].endpoints[0];
    assert(endpoint.current && endpoint.capability_valid && endpoint.effective_valid);
    assert(endpoint.capability[6] == 0 && endpoint.capability[8] == 3 &&
           endpoint.capability[12] == 1);
    assert(endpoint.effective[4] == 1 && bodaqs_control_get_u64(endpoint.effective + 144) == 9);
    assert(bodaqs_control_get_u64(endpoint.effective + 24) == 1 &&
           bodaqs_control_get_u64(endpoint.effective + 32) == 1);
    assert(bodaqs_control_get_u64(endpoint.effective + 184) == observer.nodes[0].endpoint_epoch[0]);
}
void failedBankSelectionCannotInventAuxiliaryProof()
{
    Fixture f;
    f.open();
    f.page(0);
    f.page(1);
    f.commit();
    f.finish();
    f.regs.bytes[1][4] = 0x38;
    f.regs.ignore_write = 1;
    f.open(3, 1, 2);
    f.page(0);
    f.page(1);
    f.commit();
    f.finish();
    assert(f.authority.latest_result.data[1] == 17);
}
void reservedFieldsAndInspectionWhileBackendPending()
{
    Fixture f;
    f.open();
    f.page(0);
    f.page(1);
    f.commit();
    f.finish();
    const auto resets = f.regs.resets;
    f.regs.bytes[0][16] |= 1;
    f.regs.bytes[0][18] |= 2;
    f.regs.bytes[0][8] |= 0x28;
    f.open(3, 1, 2);
    f.page(0);
    f.page(1);
    f.commit();
    f.finish();
    assert(f.authority.latest_result.data[0] == 3 && f.regs.resets == resets);
    uint8_t d[192];
    f.descriptor(d);
    assert(d[161] == 5 && d[163] == 0x46 && d[153] == 0x28);
    Fixture pending;
    pending.open();
    pending.page(0);
    pending.page(1);
    pending.commit();
    // The physical boundary remains pending. Authority, state and snapshot reads
    // remain serviceable without changing the admitted mutation or its deadline.
    pending.backend.reg = reg;
    bodaqs_control_apply_tick(&pending.apply, pending.now + 20);
    auto query = pending.begin;
    query.opcode = 0x14;
    query.operation = 75;
    query.transfer = 0;
    query.data_length = 4;
    memset(query.data, 0, 24);
    query.data[0] = 2;
    assert(bodaqs_control_authority_process(&pending.authority, &pending.view, &query,
                                            pending.now + 21, nullptr, nullptr, &pending.reply));
    assert(pending.reply.data[0] == 2 && pending.reply.data[3] == 0x14);
    query.opcode = 4;
    query.data_length = 0;
    memset(query.data, 0, 24);
    assert(bodaqs_control_node_process(&pending.view, &query, &pending.reply));
    assert(bodaqs_control_get_u32(pending.reply.data + 20) == 2);
    BodaqsControlSnapshot snapshot = {};
    snapshot.capture = bodaqs_control_apply_capture;
    snapshot.capture_context = &pending.apply;
    query.opcode = 6;
    assert(bodaqs_control_snapshot_process(&snapshot, &pending.view, &query, pending.now + 22,
                                           &pending.reply));
    assert(pending.reply.opcode == 6 && pending.view.pending_operation == 2);
    bodaqs_control_apply_tick(&pending.apply, pending.now + 2000);
    assert(pending.authority.latest_result.data[0] == 5 &&
           pending.authority.latest_result.data[1] == 18);
    Fixture wrap;
    wrap.now = UINT32_MAX - 100;
    wrap.open();
    bodaqs_control_apply_tick(&wrap.apply, wrap.now + 5000);
    assert(wrap.authority.latest_result.data[1] == 10 && !wrap.view.pending_operation);
}
int main()
{
    failedBankSelectionCannotInventAuxiliaryProof();
    reservedFieldsAndInspectionWhileBackendPending();
    stagingExpiry();
    physicalDisableAndFreshNoOp();
    invalidStagingNeverTouchesHardware();
    faultsPreserveHistoricalEvidenceAndScope();
    loggerDisabledAcrossRealSpiCanApplyAndSnapshot();
    puts("apply tests passed");
}
