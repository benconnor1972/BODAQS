#include "bodaqs_control.h"
#include "bodaqs_control_authority.h"
#include "bodaqs_control_exchange.h"
#include "bodaqs_control_observer.h"
#include <cassert>
#include <cstring>
#include <initializer_list>
void wireExchangeAndBootRecovery()
{
    BodaqsControlRecord r = {};
    r.opcode = 4;
    r.endpoint = 255;
    r.operation = 0x04030201;
    r.node_boot_id = 0x08070605;
    r.session = UINT64_C(0x100f0e0d0c0b0a09);
    uint8_t bytes[64];
    assert(bodaqs_control_encode_can(&r, false, 0x1234, bytes));
    const uint8_t expected[36] = {
        1, 16, 1, 0,  0x34, 0x12, 52, 0,  4,  255, 0, 0, 1, 2, 3, 4, 5, 6,
        7, 8,  9, 10, 11,   12,   13, 14, 15, 16,  0, 0, 0, 0, 0, 0, 0, 0};
    assert(memcmp(bytes, expected, 36) == 0);
    for (unsigned i = 36; i < 64; ++i)
    {
        assert(bytes[i] == 0);
    }
    uint16_t tx;
    BodaqsControlRecord decoded;
    assert(bodaqs_control_decode_can(bytes, 64, false, &tx, &decoded));
    bytes[63] = 1;
    assert(!bodaqs_control_decode_can(bytes, 64, false, &tx, &decoded));
    BodaqsControlObserver observer;
    bodaqs_control_observer_init(&observer);
    bodaqs_control_observer_boot(&observer, 99, 3);
    bodaqs_control_observer_node(&observer, 0, 0x08070605, 1, true);
    BodaqsControlWrapped query, answer;
    uint8_t query_type;
    assert(bodaqs_control_observer_next(&observer, &query, &query_type));
    assert(query_type == 6 && query.record.endpoint == 255);
    answer = query;
    answer.record.data_length = 24;
    bodaqs_control_put_u64(answer.record.data, UINT64_C(18446744073709551615));
    assert(bodaqs_control_observer_accept(&observer, 0x87, &answer, 123));
    assert(observer.nodes[0].valid &&
           observer.nodes[0].active_session == UINT64_MAX);
    bodaqs_control_observer_boot(&observer, 100, 3);
    assert(!observer.nodes[0].valid);
    assert(observer.master_boot_id == 100);
    BodaqsControlExchange exchange;
    bodaqs_control_exchange_init(&exchange, 99);
    BodaqsControlWrapped request = {};
    request.master_boot_id = 99;
    request.node_address = 0;
    request.record = r;
    BodaqsControlWrapped response;
    uint8_t type;
    assert(bodaqs_control_exchange_request(&exchange, false, &request,
                                           &response, &type));
    assert(type == 0x86 && response.record.data[0] == 0);
    uint8_t address;
    uint16_t transaction;
    assert(bodaqs_control_exchange_transmit(&exchange, 0, &address,
                                            &transaction, bytes));
    const uint16_t first_transaction = transaction;
    assert(!bodaqs_control_exchange_transmit(&exchange, 999, &address,
                                             &transaction, bytes));
    assert(bodaqs_control_exchange_request(&exchange, false, &request,
                                           &response, &type));
    assert(response.record.data[0] == 2);
    assert(bodaqs_control_exchange_transmit(&exchange, 1000, &address,
                                            &transaction, bytes));
    assert(transaction == first_transaction);
    assert(bodaqs_control_exchange_transmit(&exchange, 2000, &address,
                                            &transaction, bytes));
    assert(!bodaqs_control_exchange_transmit(&exchange, 3000, &address,
                                             &transaction, bytes));
    assert(bodaqs_control_exchange_request(&exchange, true, &request, &response,
                                           &type));
    assert(type == 0x86 && response.record.data[0] == 5 &&
           response.record.data[1] == 26 && response.record.data[2] == 1);
    BodaqsControlNode node = {};
    node.boot_id = r.node_boot_id;
    node.active_session = r.session;
    node.endpoint_mask = 1;
    node.endpoint_epoch[0] = 1;
    BodaqsControlRecord reply;
    assert(bodaqs_control_node_process(&node, &r, &reply));
    assert(reply.opcode == 4 && reply.data_length == 24 &&
           bodaqs_control_get_u64(reply.data + 8) == 0);
    assert(!bodaqs_control_exchange_receive(&exchange, 0, first_transaction,
                                            &reply));
    request.record.operation++;
    assert(bodaqs_control_exchange_request(&exchange, false, &request,
                                           &response, &type));
    assert(bodaqs_control_exchange_transmit(&exchange, 3001, &address,
                                            &transaction, bytes));
    assert(transaction != first_transaction);
    assert(bodaqs_control_node_process(&node, &request.record, &reply));
    assert(bodaqs_control_exchange_receive(&exchange, 0, transaction, &reply));
    assert(bodaqs_control_exchange_request(&exchange, true, &request, &response,
                                           &type));
    assert(type == 0x87 && response.record.opcode == 4);
}

void nodeDistinguishesUnsupportedStaleAndMalformed()
{
    BodaqsControlNode node = {};
    node.boot_id = 1;
    node.endpoint_mask = 1;
    node.endpoint_epoch[0] = UINT64_C(0x8877665544332211);
    BodaqsControlRecord request = {}, reply;
    request.opcode = 4;
    request.endpoint = 0;
    request.operation = 1;
    request.node_boot_id = 1;
    request.session = 123;
    assert(bodaqs_control_node_process(&node, &request, &reply));
    assert(reply.opcode == BODAQS_CONTROL_ERROR && reply.data[1] == 5);
    request.session = 0;
    assert(bodaqs_control_node_process(&node, &request, &reply));
    const uint8_t state[24] = {0,    0,    0,    0,    0,    0,    0,    0,
                               0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88,
                               0,    0,    0,    0,    0,    0,    0,    0};
    assert(reply.opcode == 4 && reply.data_length == 24 &&
           memcmp(reply.data, state, 24) == 0);
    request.node_boot_id = 2;
    assert(bodaqs_control_node_process(&node, &request, &reply));
    assert(reply.opcode == 127 && reply.data[0] == 1 && reply.data[1] == 4 &&
           reply.data[2] == 5 && reply.data[3] == 4);
    request.node_boot_id = 1;
    request.endpoint = 1;
    assert(bodaqs_control_node_process(&node, &request, &reply));
    assert(reply.opcode == 127 && reply.data[1] == 23 && reply.data[2] == 19);
    request.endpoint = 0;
    request.opcode = 7;
    request.transfer = 1;
    request.page = 2;
    assert(bodaqs_control_node_process(&node, &request, &reply));
    assert(reply.opcode == 127 && reply.page == 2 && reply.data[1] == 1 &&
           reply.data[3] == 7);
    request.opcode = 0x70;
    request.transfer = 0;
    request.page = 0;
    assert(bodaqs_control_node_process(&node, &request, &reply));
    assert(reply.opcode == 127 && reply.data[1] == 1 && reply.data[3] == 0x70);
    request.opcode = 4;
    request.operation = 0;
    assert(!bodaqs_control_node_process(&node, &request, &reply));
    request.operation = 1;
    request.transfer = 1;
    assert(!bodaqs_control_node_process(&node, &request, &reply));
    request.transfer = 0;
    request.page = 1;
    assert(!bodaqs_control_node_process(&node, &request, &reply));
    request.page = 0;
    request.endpoint = 6;
    assert(!bodaqs_control_node_process(&node, &request, &reply));
    request.endpoint = 0;
    request.data[23] = 1;
    assert(!bodaqs_control_node_process(&node, &request, &reply));
}
void wrappersEnforceVersionReservedAndIndependentOffsets()
{
    const uint8_t wire[64] = {1,  2,  3,  4,   5,  6,  7,  8,  3,  1,
                              0,  0,  4,  255, 0,  0,  9,  10, 11, 12,
                              13, 14, 15, 16,  17, 18, 19, 20, 21, 22,
                              23, 24, 25, 26,  27, 28, 29, 30, 31, 32};
    BodaqsControlWrapped parsed;
    assert(bodaqs_control_decode_wrapped(wire, 64, &parsed));
    assert(parsed.master_boot_id == UINT64_C(0x0807060504030201) &&
           parsed.node_address == 3);
    assert(parsed.record.operation == 0x0c0b0a09 &&
           parsed.record.node_boot_id == 0x100f0e0d);
    assert(parsed.record.session == UINT64_C(0x1817161514131211) &&
           parsed.record.transfer == UINT64_C(0x201f1e1d1c1b1a19));
    uint8_t encoded[64];
    assert(bodaqs_control_encode_wrapped(&parsed, encoded));
    assert(memcmp(encoded, wire, 64) == 0);
    for (unsigned offset : {9U, 10U, 11U})
    {
        memcpy(encoded, wire, 64);
        encoded[offset] = 2;
        assert(!bodaqs_control_decode_wrapped(encoded, 64, &parsed));
    }
    assert(!bodaqs_control_decode_wrapped(wire, 63, &parsed));
}
void conflictingPendingAndLateIdentitiesCannotReplaceAnExchange()
{
    BodaqsControlExchange master;
    bodaqs_control_exchange_init(&master, 1);
    BodaqsControlWrapped first = {}, reply, other;
    first.master_boot_id = 1;
    first.record.opcode = 4;
    first.record.endpoint = 255;
    first.record.operation = 1;
    first.record.node_boot_id = 1;
    uint8_t type;
    assert(
        bodaqs_control_exchange_request(&master, false, &first, &reply, &type));
    other = first;
    other.record.operation = 2;
    assert(
        bodaqs_control_exchange_request(&master, false, &other, &reply, &type));
    assert(type == 0x86 && reply.record.data[0] == 3 &&
           reply.record.data[1] == 7);
    uint8_t address, payload[64];
    uint16_t tx;
    assert(bodaqs_control_exchange_transmit(&master, UINT32_MAX - 500, &address,
                                            &tx, payload));
    assert(!bodaqs_control_exchange_transmit(&master, 498, &address, &tx,
                                             payload));
    assert(
        bodaqs_control_exchange_transmit(&master, 499, &address, &tx, payload));
    BodaqsControlNode node = {};
    node.boot_id = 1;
    BodaqsControlRecord result;
    assert(bodaqs_control_node_process(&node, &other.record, &result));
    assert(!bodaqs_control_exchange_receive(&master, 0, tx, &result));
    assert(bodaqs_control_node_process(&node, &first.record, &result));
    assert(bodaqs_control_exchange_receive(&master, 0, tx, &result));
    master.next_transaction = 65535;
    assert(
        bodaqs_control_exchange_request(&master, false, &other, &reply, &type));
    assert(bodaqs_control_exchange_transmit(&master, 500, &address, &tx,
                                            payload) &&
           tx == 65535);
    assert(bodaqs_control_node_process(&node, &other.record, &result));
    assert(bodaqs_control_exchange_receive(&master, 0, tx, &result));
    other.record.operation = 3;
    assert(
        bodaqs_control_exchange_request(&master, false, &other, &reply, &type));
    assert(bodaqs_control_exchange_transmit(&master, 501, &address, &tx,
                                            payload) &&
           tx == 1);
    assert(!bodaqs_control_exchange_receive(&master, 0, tx, &result));
}
// Run the real snapshot/observer exchange so health captured before a transition
// cannot pass the final fresh endpoint-state check.
void clockHealthInvalidatesCapturedSnapshot()
{
    BodaqsControlNode node = {};
    node.boot_id = 55;
    node.endpoint_mask = 1;
    node.endpoint_epoch[0] = 1;
    BodaqsControlSnapshot snapshot = {};
    BodaqsControlObserver observer;
    bodaqs_control_observer_init(&observer);
    bodaqs_control_observer_boot(&observer, 99, 3);
    bodaqs_control_observer_node(&observer, 0, 55, 1, true);
    bool changed = false, refreshed = false;
    for (unsigned step = 0; step < 32 && !refreshed; ++step)
    {
        BodaqsControlWrapped query, answer;
        uint8_t type;
        assert(bodaqs_control_observer_next(&observer, &query, &type));
        answer = query;
        assert(bodaqs_control_snapshot_process(&snapshot, &node, &query.record,
                                               step, &answer.record) ||
               bodaqs_control_node_process(&node, &query.record, &answer.record));
        if (query.record.opcode == BODAQS_CONTROL_OPEN_EFFECTIVE)
        {
            assert(bodaqs_control_node_update_clock_fault(&node, true));
            changed = true;
        }
        assert(bodaqs_control_observer_accept(&observer,
                    BODAQS_CONTROL_POLL_RESPONSE, &answer, step));
        if (changed && query.record.opcode == BODAQS_CONTROL_GET_NODE_STATE)
            refreshed = true;
    }
    assert(refreshed);
    const auto& endpoint = observer.nodes[0].endpoints[0];
    assert(endpoint.effective_valid);
    assert(bodaqs_control_get_u32(endpoint.effective + 20) == 32);
    assert(bodaqs_control_get_u64(endpoint.effective + 184) == 1);
    assert(observer.nodes[0].endpoint_epoch[0] == 2);
    assert(observer.nodes[0].flags & (1U << 7));
    assert(!endpoint.current);
}
void clockHealthChangesOnlyFittedEpochsAndFailsClosedAtExhaustion()
{
    BodaqsControlNode node = {};
    node.boot_id = 55;
    node.active_session = 99;
    node.flags = 1;
    node.endpoint_mask = 5;
    node.endpoint_epoch[0] = 8;
    node.endpoint_epoch[1] = UINT64_MAX; // unfitted endpoints consume nothing
    node.endpoint_epoch[2] = UINT64_MAX - 1;
    assert(bodaqs_control_node_update_clock_fault(&node, true));
    assert(node.endpoint_epoch[0] == 9 && node.endpoint_epoch[2] == UINT64_MAX);
    assert(node.flags == 129);
    assert(bodaqs_control_node_update_clock_fault(&node, true));
    assert(node.endpoint_epoch[0] == 9 && node.endpoint_epoch[2] == UINT64_MAX);
    assert(!bodaqs_control_node_update_clock_fault(&node, false));
    assert(node.endpoint_epoch[0] == 9 && node.endpoint_epoch[2] == UINT64_MAX);
    assert(node.boot_id == 55 && node.active_session == 99 && node.flags == 129);
    // Exhaustion stays closed even if health later returns to its prior value.
    assert(!bodaqs_control_node_update_clock_fault(&node, true));
    BodaqsControlRecord query = {}, reply;
    query.opcode = BODAQS_CONTROL_GET_NODE_STATE;
    query.node_boot_id = 55;
    query.operation = 1;
    assert(bodaqs_control_node_process(&node, &query, &reply));
    assert(reply.opcode == BODAQS_CONTROL_ERROR && reply.data[1] == 22);
    BodaqsControlSnapshot snapshot = {};
    query.opcode = BODAQS_CONTROL_OPEN_EFFECTIVE;
    assert(bodaqs_control_snapshot_process(&snapshot, &node, &query, 0, &reply));
    assert(reply.opcode == BODAQS_CONTROL_ERROR && reply.data[1] == 22);
    BodaqsControlAuthority authority = {};
    query.opcode = BODAQS_CONTROL_RELEASE_SESSION;
    query.session = 99;
    query.endpoint = BODAQS_CONTROL_NODE_WIDE;
    assert(bodaqs_control_authority_process(&authority, &node, &query, 0,
                                          nullptr, nullptr, &reply));
    assert(reply.opcode == BODAQS_CONTROL_ERROR && reply.data[1] == 22);
    // Boot mismatch still wins before any exhausted-state semantics.
    query.node_boot_id = 54;
    assert(bodaqs_control_authority_process(&authority, &node, &query, 0,
                                          nullptr, nullptr, &reply));
    assert(reply.data[1] == 4);
    assert(bodaqs_control_authority_admit(&authority, &node, &query) == 4);
    query.opcode = BODAQS_CONTROL_OPEN_EFFECTIVE;
    query.endpoint = 0;
    assert(bodaqs_control_snapshot_process(&snapshot, &node, &query, 0, &reply));
    assert(reply.data[1] == 4);
    query.opcode = BODAQS_CONTROL_GET_NODE_STATE;
    assert(bodaqs_control_node_process(&node, &query, &reply));
    assert(reply.data[1] == 4);

    node = {};
    node.endpoint_mask = 1;
    node.endpoint_epoch[0] = 1;
    assert(bodaqs_control_node_update_clock_fault(&node, false));
    assert(node.endpoint_epoch[0] == 1);
    assert(bodaqs_control_node_update_clock_fault(&node, true));
    assert(bodaqs_control_node_update_clock_fault(&node, false));
    assert(node.endpoint_epoch[0] == 3 && node.flags == 0);
    assert(bodaqs_control_node_update_clock_fault(&node, false));
    assert(node.endpoint_epoch[0] == 3);
}
int main()
{
    assert(strcmp(bodaqs_control_reason_key(26), "can_exchange_timeout") == 0);
    assert(strcmp(bodaqs_control_reason_key(255), "unknown") == 0);
    clockHealthInvalidatesCapturedSnapshot();
    clockHealthChangesOnlyFittedEpochsAndFailsClosedAtExhaustion();
    wireExchangeAndBootRecovery();
    nodeDistinguishesUnsupportedStaleAndMalformed();
    wrappersEnforceVersionReservedAndIndependentOffsets();
    conflictingPendingAndLateIdentitiesCannotReplaceAnExchange();
}
