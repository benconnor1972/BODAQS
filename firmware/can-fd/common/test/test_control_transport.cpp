#include "CanMasterProtocol.h"
#include "bodaqs_control_authority.h"
#include "bodaqs_control_authority_client.h"
#include "bodaqs_control_observer.h"
#include "bodaqs_master_service.h"
#include "../network/bodaqs_node_inventory.h"
#include <cassert>
#include <cstring>
#include <initializer_list>

namespace
{
CanMasterProtocol::Frame spi(BodaqsMasterService &master, uint8_t type,
                             const BodaqsControlWrapped *wrapped = nullptr)
{
    CanMasterProtocol::Frame request, reply;
    request.type = static_cast<CanMasterProtocol::MessageType>(type);
    request.sequence = 0x12345678;
    if (wrapped)
    {
        request.payloadLength = 64;
        assert(bodaqs_control_encode_wrapped(wrapped, request.payload));
    }
    uint8_t tx[84], rx[84];
    assert(CanMasterProtocol::encodeSlot(request, tx, 84));
    assert(bodaqs_master_service_process_slot(&master, tx, rx) ==
           BODAQS_MASTER_SLOT_PROCESSED);
    assert(CanMasterProtocol::decodeSlot(rx, 84, reply) ==
           CanMasterProtocol::DecodeResult::Ok);
    assert(reply.sequence == 0x12345678);
    return reply;
}
// Publish the actual powered-interval inventory latch through the production
// service boundary, as the master's main loop does after receiving announces.
void announce(BodaqsNodeInventory &inventory, BodaqsMasterService &master,
              uint64_t uid)
{
    BodaqsCanNodeAnnounce node = {};
    node.hardware_uid = uid;
    node.boot_id = 123;
    (void)bodaqs_node_inventory_observe_announce(&inventory, &node, 10);
    BodaqsMasterDiscoveryRecord records[4] = {};
    for (unsigned i = 0; i < 4; ++i) {
        const auto &entry = inventory.nodes[i];
        records[i].flags = (entry.present ? BODAQS_MASTER_DISCOVERY_FLAG_PRESENT : 0) |
            (entry.duplicate ? BODAQS_MASTER_DISCOVERY_FLAG_DUPLICATE : 0);
        records[i].hardware_uid = entry.identity.hardware_uid;
        records[i].conflicting_hardware_uid = entry.conflicting_hardware_uid;
    }
    bodaqs_master_service_set_inventory(&master, inventory.generation, records, 4);
}
BodaqsControlWrapped commitRequest()
{
    BodaqsControlWrapped q = {};
    q.master_boot_id = 99;
    auto &r = q.record;
    r.opcode = BODAQS_CONTROL_COMMIT_APPLY;
    r.node_boot_id = 123; r.session = 456; r.operation = 2; r.transfer = 789;
    r.data_length = 24; r.data[0] = 1; r.data[2] = 1; r.data[4] = 44; r.data[8] = 1;
    return q;
}
void duplicateInventoryBlocksNewConfiguration()
{
    BodaqsMasterService master;
    bodaqs_master_service_init(&master, nullptr);
    bodaqs_control_exchange_init(&master.control, 99);
    BodaqsNodeInventory inventory;
    bodaqs_node_inventory_init(&inventory);
    announce(inventory, master, 11);
    announce(inventory, master, 22);
    assert(inventory.nodes[0].duplicate);
    auto q = commitRequest();
    auto result = spi(master, 6, &q);
    BodaqsControlWrapped reply;
    assert(bodaqs_control_decode_wrapped(result.payload, 64, &reply));
    assert(result.type == CanMasterProtocol::MessageType::ControlReceiptResponse);
    assert(reply.record.data[0] == 3 && reply.record.data[1] == 7);
    uint8_t address, wire[64]; uint16_t transaction;
    assert(!bodaqs_control_exchange_transmit(&master.control, 0, &address, &transaction, wire));
    // The duplicate latch does not block independent addresses or inspection.
    q.node_address = 1;
    (void)spi(master, 6, &q);
    assert(bodaqs_control_exchange_transmit(&master.control, 0, &address, &transaction, wire));
    assert(address == 1);
    q = {}; q.master_boot_id = 99;
    q.record.opcode = 4; q.record.endpoint = 255;
    q.record.operation = 1; q.record.node_boot_id = 123;
    (void)spi(master, 6, &q);
    assert(bodaqs_control_exchange_transmit(&master.control, 1, &address, &transaction, wire));
    assert(address == 0);
}
void duplicateDuringExchangePreventsDispatchAndRetry(bool transmitted)
{
    BodaqsMasterService master;
    bodaqs_master_service_init(&master, nullptr);
    bodaqs_control_exchange_init(&master.control, 99);
    BodaqsNodeInventory inventory;
    bodaqs_node_inventory_init(&inventory);
    announce(inventory, master, 11);
    auto q = commitRequest();
    (void)spi(master, 6, &q);
    uint8_t address, wire[64]; uint16_t transaction = 0;
    if (transmitted) {
        assert(bodaqs_control_exchange_transmit(&master.control, 0, &address, &transaction, wire));
        BodaqsControlRecord decoded; uint16_t decodedTransaction;
        assert(bodaqs_control_decode_can(wire, 64, false, &decodedTransaction, &decoded));
        assert(decoded.opcode == BODAQS_CONTROL_COMMIT_APPLY && address == 0);
    }
    announce(inventory, master, 22);
    // Neither initial dispatch nor the one-second retry may cross the latch.
    assert(!bodaqs_control_exchange_transmit(&master.control, 1000, &address, &transaction, wire));
    assert(!bodaqs_control_exchange_transmit(&master.control, 10000, &address, &transaction, wire));
    BodaqsControlWrapped reply;
    for (uint8_t type : {uint8_t(6), uint8_t(7)}) {
        auto request = q;
        if (type == 7) { request.record.data_length = 0; memset(request.record.data, 0, 24); }
        auto result = spi(master, type, &request);
        assert(result.type == CanMasterProtocol::MessageType::ControlReceiptResponse);
        assert(bodaqs_control_decode_wrapped(result.payload, 64, &reply));
        assert(reply.record.data[0] == (transmitted ? 5 : 3));
        assert(reply.record.data[1] == (transmitted ? 26 : 7));
        assert(reply.record.data[3] == BODAQS_CONTROL_COMMIT_APPLY);
    }
    // A late accepted reply cannot turn the excluded route into current proof.
    if (transmitted) {
        auto late = q.record; late.data[0] = 3;
        assert(!bodaqs_control_exchange_receive(&master.control, 0, transaction, &late));
    }
    // A fresh mutation remains blocked; silence and the original UID do not
    // clear the inventory's powered-interval duplicate latch.
    bodaqs_node_inventory_update_stale(&inventory, 100000, 100);
    announce(inventory, master, 11);
    ++q.record.operation;
    auto result = spi(master, 6, &q);
    assert(bodaqs_control_decode_wrapped(result.payload, 64, &reply));
    assert(reply.record.data[0] == 3 && reply.record.data[1] == 7);
    assert(!bodaqs_control_exchange_transmit(&master.control, 100001, &address, &transaction, wire));
}
void loggerReadsNodeStateThroughBothRealTransports()
{
    BodaqsMasterService master;
    bodaqs_master_service_init(&master, nullptr);
    bodaqs_control_exchange_init(&master.control, UINT64_C(0x0807060504030201));
    auto info = spi(master, 5);
    const uint8_t expected[32] = {1, 2, 3, 4, 5, 6, 7, 8,  3,  0, 0,
                                  0, 1, 0, 1, 0, 0, 2, 24, 16, 4, 1,
                                  0, 0, 1, 0, 0, 0, 0, 0,  0,  0};
    assert(info.type == CanMasterProtocol::MessageType::ControlInfoResponse);
    assert(info.payloadLength == 32 && memcmp(info.payload, expected, 32) == 0);
    BodaqsControlObserver logger;
    bodaqs_control_observer_init(&logger);
    uint64_t boot;
    uint32_t features;
    assert(bodaqs_control_decode_info(info.payload, 32, &boot, &features));
    bodaqs_control_observer_boot(&logger, boot, features);
    bodaqs_control_observer_node(&logger, 2, 55, 1, true);
    BodaqsControlWrapped request, reply;
    uint8_t type;
    assert(bodaqs_control_observer_next(&logger, &request, &type));
    auto receipt = spi(master, type, &request);
    assert(receipt.type ==
           CanMasterProtocol::MessageType::ControlReceiptResponse);
    assert(bodaqs_control_decode_wrapped(receipt.payload, 64, &reply));
    assert(reply.record.data[0] == 0);
    assert(bodaqs_control_observer_accept(&logger, 0x86, &reply, 0));
    uint8_t address, can[64];
    uint16_t tx;
    assert(bodaqs_control_exchange_transmit(&master.control, 0, &address, &tx,
                                            can));
    assert(address == 2);
    BodaqsControlRecord nodeRequest, nodeReply;
    uint16_t nodeTransaction;
    assert(bodaqs_control_decode_can(can, 64, false, &nodeTransaction,
                                     &nodeRequest));
    BodaqsControlNode node = {};
    node.boot_id = 55;
    node.endpoint_mask = 1;
    node.endpoint_epoch[0] = UINT64_MAX;
    node.active_session = UINT64_C(0x8877665544332211);
    node.flags = 1;
    assert(bodaqs_control_node_process(&node, &nodeRequest, &nodeReply));
    assert(bodaqs_control_encode_can(&nodeReply, true, nodeTransaction, can));
    assert(bodaqs_control_decode_can(can, 64, true, &tx, &nodeReply));
    assert(bodaqs_control_exchange_receive(&master.control, address, tx,
                                           &nodeReply));
    assert(bodaqs_control_observer_next(&logger, &request, &type) && type == 7);
    auto completed = spi(master, type, &request);
    assert(completed.type ==
           CanMasterProtocol::MessageType::ControlPollResponse);
    assert(bodaqs_control_decode_wrapped(completed.payload, 64, &reply));
    assert(bodaqs_control_observer_accept(&logger, 0x87, &reply, 10));
    assert(logger.nodes[2].valid &&
           logger.nodes[2].active_session == UINT64_C(0x8877665544332211));
    assert(logger.nodes[2].flags == 1);
    // The next read inspects the endpoint without acquiring authority.
    assert(bodaqs_control_observer_next(&logger, &request, &type) &&
           request.record.endpoint == 0);
    (void)spi(master, type, &request);
    assert(bodaqs_control_exchange_transmit(&master.control, 11, &address, &tx,
                                            can));
    assert(bodaqs_control_node_process(&node, &request.record, &nodeReply));
    assert(bodaqs_control_exchange_receive(&master.control, address, tx,
                                           &nodeReply));
    completed = spi(master, 7, &request);
    assert(bodaqs_control_decode_wrapped(completed.payload, 64, &reply));
    assert(bodaqs_control_observer_accept(&logger, 0x87, &reply, 12));
    assert(logger.nodes[2].epoch_valid_mask == 1 &&
           logger.nodes[2].endpoint_epoch[0] == UINT64_MAX);
    // A new master reports its current boot on stale submissions; invalidate.
    bodaqs_control_exchange_init(&master.control, 100);
    assert(bodaqs_control_observer_next(&logger, &request, &type));
    receipt = spi(master, type, &request);
    assert(bodaqs_control_decode_wrapped(receipt.payload, 64, &reply));
    assert(reply.record.data[0] == 4 && reply.record.data[1] == 25 &&
           reply.record.data[2] == 7);
    assert(!bodaqs_control_observer_accept(&logger, 0x86, &reply, 20));
    assert(!logger.nodes[2].valid && !logger.nodes[2].epoch_valid_mask);
}
void malformedTypedSlotReservedBytesAreDiscarded()
{
    BodaqsMasterService master;
    bodaqs_master_service_init(&master, nullptr);
    bodaqs_control_exchange_init(&master.control, 99);
    CanMasterProtocol::Frame request;
    request.type = CanMasterProtocol::MessageType::ControlInfoRequest;
    request.sequence = 1;
    uint8_t tx[84], rx[84];
    assert(CanMasterProtocol::encodeSlot(request, tx, 84));
    tx[14] = 1;
    bodaqs_control_put_u32(tx + 80, CanMasterProtocol::crc32(tx, 80));
    assert(bodaqs_master_service_process_slot(&master, tx, rx) ==
           BODAQS_MASTER_SLOT_MALFORMED);
    for (auto byte : rx)
    {
        assert(byte == 0);
    }
}
void malformedNodeCompletionCannotWedgeInspection()
{
    BodaqsControlExchange master;
    bodaqs_control_exchange_init(&master, 99);
    BodaqsControlWrapped request = {}, response;
    request.master_boot_id = 99;
    request.record.opcode = 4;
    request.record.endpoint = 255;
    request.record.operation = 1;
    request.record.node_boot_id = 1;
    uint8_t type, address, wire[64];
    uint16_t transaction;
    assert(bodaqs_control_exchange_request(&master, false, &request, &response,
                                           &type));
    assert(bodaqs_control_exchange_transmit(&master, 0, &address, &transaction,
                                            wire));
    BodaqsControlRecord malformed = request.record;
    assert(!bodaqs_control_exchange_receive(&master, address, transaction,
                                            &malformed));
    // A proper reply remains admissible after rejecting the malformed result.
    BodaqsControlNode node = {};
    node.boot_id = 1;
    assert(bodaqs_control_node_process(&node, &request.record, &malformed));
    assert(bodaqs_control_exchange_receive(&master, address, transaction,
                                           &malformed));
    BodaqsControlObserver logger;
    bodaqs_control_observer_init(&logger);
    bodaqs_control_observer_boot(&logger, 99, 3);
    bodaqs_control_observer_node(&logger, 0, 1, 0, true);
    assert(bodaqs_control_observer_next(&logger, &request, &type));
    response = request; // A buggy peer has cached an empty GET_STATE result.
    assert(!bodaqs_control_observer_accept(&logger, 0x87, &response, 0));
    assert(!logger.pending && !logger.nodes[0].valid);
    assert(bodaqs_control_observer_next(&logger, &request, &type));
    assert(type == 6 && request.record.operation == 2);
}

void snapshotsCrossBothLinksWithinLifetime(bool corrupt, bool lose = false)
{
    BodaqsMasterService master;
    bodaqs_master_service_init(&master, nullptr);
    bodaqs_control_exchange_init(&master.control, 99);
    BodaqsControlObserver logger;
    bodaqs_control_observer_init(&logger);
    bodaqs_control_observer_boot(&logger, 99, 3);
    BodaqsControlNode nodes[4] = {};
    BodaqsControlSnapshot snapshots[4] = {};
    for (unsigned i = 0; i < 4; i++)
    {
        nodes[i].boot_id = 55 + i;
        nodes[i].endpoint_mask = 1;
        nodes[i].endpoint_epoch[0] = 1;
        bodaqs_control_observer_node(&logger, (uint8_t)i, 55 + i, 1, true);
    }
    bool corrupted = false;
    for (uint32_t now = 0; now < 30000; now += 100)
    {
        bodaqs_control_observer_tick(&logger, now);
        BodaqsControlWrapped q, r;
        uint8_t type;
        if (lose && now >= 10000)
        {
            assert(!logger.nodes[0].endpoints[0].effective_valid);
            assert(!logger.nodes[0].endpoints[0].current);
            return;
        }
        assert(bodaqs_control_observer_next(&logger, &q, &type));
        auto result = spi(master, type, &q);
        assert(bodaqs_control_decode_wrapped(result.payload,
                                             result.payloadLength, &r));
        bool accepted = bodaqs_control_observer_accept(
            &logger, (uint8_t)result.type, &r, now);
        if (!accepted)
        {
            assert(corrupt);
            assert(!logger.nodes[q.node_address].endpoints[0].current);
            return;
        }
        uint8_t address, wire[64];
        uint16_t transaction;
        if (bodaqs_control_exchange_transmit(&master.control, now, &address,
                                             &transaction, wire))
        {
            BodaqsControlRecord nq, nr;
            uint16_t nt;
            assert(bodaqs_control_decode_can(wire, 64, false, &nt, &nq));
            if (lose && nq.opcode == BODAQS_CONTROL_READ_PAGE && nq.page == 3 &&
                snapshots[address].length == 192)
                continue;
            assert(bodaqs_control_snapshot_process(
                       &snapshots[address], &nodes[address], &nq, now, &nr) ||
                   bodaqs_control_node_process(&nodes[address], &nq, &nr));
            if (corrupt && nq.opcode == 7 && nq.page == 1 && !corrupted)
            {
                nr.data[7] = 1;
                corrupted = true;
            }
            assert(bodaqs_control_encode_can(&nr, true, nt, wire));
            assert(bodaqs_control_decode_can(wire, 64, true, &nt, &nr));
            assert(bodaqs_control_exchange_receive(&master.control, address, nt,
                                                   &nr));
        }
        bool all = true;
        for (unsigned i = 0; i < 4; i++)
        {
            const auto &ep = logger.nodes[i].endpoints[0];
            all =
                all && ep.current && ep.capability_valid && ep.effective_valid;
            if (ep.effective_valid)
            {
                assert(ep.effective[4] == 0);
                assert(bodaqs_control_get_u32(ep.effective + 12) == 0);
                assert(bodaqs_control_get_u32(ep.effective + 120) == 0);
                assert(ep.capability[6] == 0 &&
                       bodaqs_control_get_u32(ep.capability + 8) == 0);
            }
        }
        if (all)
        {
            assert(!corrupt);
            return;
        }
    }
    assert(false &&
           "snapshot pages must complete at 100ms SPI cadence for four nodes");
}
uint64_t authorityEntropy(void *) { return 0x123456789abcdef0ULL; }
void authoritySurvivesLostCanBindAndReleaseReplies()
{
    BodaqsMasterService master;
    bodaqs_master_service_init(&master, nullptr);
    bodaqs_control_exchange_init(&master.control, 99);
    BodaqsControlAuthority authority;
    bodaqs_control_authority_init(&authority);
    BodaqsControlAuthorityClient logger;
    bodaqs_control_authority_client_init(&logger, 0x1020304050607080ULL);
    bodaqs_control_authority_client_node(&logger, 0, 55, true);
    BodaqsControlNode node = {};
    node.boot_id = 55;
    node.endpoint_mask = 1;
    node.endpoint_epoch[0] = 1;
    bool lostBind = false, lostRelease = false, releaseRequested = false;
    for (uint32_t now = 0; now < 10000; now += 100)
    {
        if (logger.nodes[0].bound && !releaseRequested)
        {
            assert(node.active_session == logger.session && node.flags == 1);
            assert(bodaqs_control_authority_client_release(&logger, 0));
            releaseRequested = true;
        }
        BodaqsControlWrapped q, r;
        uint8_t type;
        if (!bodaqs_control_authority_client_next(&logger, 99, &q, &type))
        {
            assert(releaseRequested && !logger.nodes[0].bound &&
                   !node.active_session);
            assert(lostBind && lostRelease && node.endpoint_epoch[0] == 3);
            // Discovery of another node boot immediately removes local
            // authority.
            bodaqs_control_authority_client_node(&logger, 0, 56, true);
            assert(!logger.nodes[0].bound);
            return;
        }
        auto result = spi(master, type, &q);
        assert(bodaqs_control_decode_wrapped(result.payload,
                                             result.payloadLength, &r));
        assert(bodaqs_control_authority_client_accept(
            &logger, (uint8_t)result.type, &r, now));
        bodaqs_control_exchange_tick(&master.control, now);
        uint8_t address, wire[64];
        uint16_t transaction;
        if (bodaqs_control_exchange_transmit(&master.control, now, &address,
                                             &transaction, wire))
        {
            BodaqsControlRecord nq, nr;
            uint16_t nt;
            assert(bodaqs_control_decode_can(wire, 64, false, &nt, &nq));
            assert(bodaqs_control_authority_process(
                &authority, &node, &nq, now, authorityEntropy, nullptr, &nr));
            if (nq.opcode == 2 && !lostBind)
            {
                lostBind = true;
                continue;
            }
            if (nq.opcode == 3 && !lostRelease)
            {
                lostRelease = true;
                continue;
            }
            assert(bodaqs_control_encode_can(&nr, true, nt, wire));
            assert(bodaqs_control_decode_can(wire, 64, true, &nt, &nr));
            assert(bodaqs_control_exchange_receive(&master.control, address, nt,
                                                   &nr));
        }
    }
    assert(false &&
           "lost authority replies must converge under bounded master retries");
}
} // namespace
int main()
{
    duplicateInventoryBlocksNewConfiguration();
    duplicateDuringExchangePreventsDispatchAndRetry(false);
    duplicateDuringExchangePreventsDispatchAndRetry(true);
    authoritySurvivesLostCanBindAndReleaseReplies();
    snapshotsCrossBothLinksWithinLifetime(false);
    snapshotsCrossBothLinksWithinLifetime(true);
    snapshotsCrossBothLinksWithinLifetime(false, true);
    loggerReadsNodeStateThroughBothRealTransports();
    malformedTypedSlotReservedBytesAreDiscarded();
    malformedNodeCompletionCannotWedgeInspection();
}
