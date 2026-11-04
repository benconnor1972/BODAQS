#include "CanMasterProtocol.h"
#include "bodaqs_control_observer.h"
#include "bodaqs_master_service.h"
#include <cassert>
#include <cstring>

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
    (void) spi(master, type, &request);
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
    assert(bodaqs_control_exchange_request(&master, false, &request, &response, &type));
    assert(bodaqs_control_exchange_transmit(&master, 0, &address, &transaction, wire));
    BodaqsControlRecord malformed = request.record;
    assert(!bodaqs_control_exchange_receive(&master, address, transaction, &malformed));
    // A proper reply remains admissible after rejecting the malformed result.
    BodaqsControlNode node = {};
    node.boot_id = 1;
    assert(bodaqs_control_node_process(&node, &request.record, &malformed));
    assert(bodaqs_control_exchange_receive(&master, address, transaction, &malformed));
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
} // namespace
int main()
{
    loggerReadsNodeStateThroughBothRealTransports();
    malformedTypedSlotReservedBytesAreDiscarded();
    malformedNodeCompletionCannotWedgeInspection();
}
