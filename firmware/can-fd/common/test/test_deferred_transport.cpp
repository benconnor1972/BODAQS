#include <cassert>
#include <cstring>
#include "../transport/bodaqs_record_queue.h"
#include "../protocol/bodaqs_master_service.h"
#include "CanMasterProtocol.h"

static void test_whole_records_survive_overflow_and_wrap()
{
    uint8_t storage[2][BODAQS_MASTER_SLOT_BYTES];
    uint8_t first[BODAQS_MASTER_SLOT_BYTES] = {0x11};
    uint8_t second[BODAQS_MASTER_SLOT_BYTES] = {0x22};
    uint8_t output[BODAQS_MASTER_SLOT_BYTES] = {0};
    BodaqsRecordQueue queue;
    bodaqs_record_queue_init(&queue, storage, sizeof(first), 2);
    assert(!bodaqs_record_queue_pop(&queue, output));
    assert(bodaqs_record_queue_push(&queue, first));
    assert(bodaqs_record_queue_push(&queue, second));
    assert(!bodaqs_record_queue_push(&queue, output));
    assert(queue.capacity == 2 && queue.depth == 2);
    assert(queue.high_water == 2 && queue.dropped == 1);
    memset(first, 0xFF, sizeof(first)); // producer may reuse its DMA buffer
    assert(bodaqs_record_queue_pop(&queue, output));
    assert(output[0] == 0x11 && output[83] == 0);
    assert(bodaqs_record_queue_push(&queue, first)); // wrap without reordering
    assert(bodaqs_record_queue_pop(&queue, output) && output[0] == 0x22);
    assert(bodaqs_record_queue_pop(&queue, output) && output[83] == 0xFF);
    assert(!bodaqs_record_queue_pop(&queue, output));
    assert(queue.dropped == 1 && queue.high_water == 2);
}

// Exercise the handoff together with the real logger codec and master service.
// A CAN backlog uses a separate queue and cannot consume the SPI record slot.
static void test_queued_bootstrap_is_deferred_and_preserves_response()
{
    uint8_t spi_storage[1][BODAQS_MASTER_SLOT_BYTES];
    uint8_t can_storage[2][BODAQS_MASTER_SLOT_BYTES];
    uint8_t dma[BODAQS_MASTER_SLOT_BYTES] = {};
    uint8_t record[BODAQS_MASTER_SLOT_BYTES] = {};
    uint8_t response[BODAQS_MASTER_SLOT_BYTES] = {};
    BodaqsRecordQueue spi, can;
    bodaqs_record_queue_init(&spi, spi_storage, sizeof(dma), 1);
    bodaqs_record_queue_init(&can, can_storage, sizeof(dma), 2);
    BodaqsMasterIdentity identity = {};
    identity.hardware_uid = UINT64_C(0x1122334455667788);
    identity.minimum_protocol_version = 1;
    identity.maximum_protocol_version = 1;
    BodaqsMasterService service;
    bodaqs_master_service_init(&service, &identity);
    CanMasterProtocol::Frame probe;
    probe.type = CanMasterProtocol::MessageType::ProbeRequest;
    probe.sequence = 0x12345678;
    assert(CanMasterProtocol::encodeSlot(probe, dma, sizeof(dma)));
    assert(bodaqs_record_queue_push(&can, dma));
    assert(bodaqs_record_queue_push(&can, dma));
    assert(!bodaqs_record_queue_push(&can, dma));
    assert(bodaqs_record_queue_push(&spi, dma));
    memset(dma, 0, sizeof(dma));
    assert(service.slots_received == 0 && service.probes_received == 0);
    assert(bodaqs_record_queue_pop(&spi, record));
    assert(bodaqs_master_service_process_slot(&service, record, response) ==
        BODAQS_MASTER_SLOT_PROCESSED);
    assert(can.depth == 2 && can.dropped == 1);
    CanMasterProtocol::Frame decoded;
    assert(CanMasterProtocol::decodeSlot(response, sizeof(response), decoded) ==
        CanMasterProtocol::DecodeResult::Ok);
    CanMasterProtocol::Identity actual;
    assert(CanMasterProtocol::decodeIdentity(decoded, actual));
    assert(decoded.sequence == 0x12345678);
    assert(actual.hardwareUid == UINT64_C(0x1122334455667788));
    assert(service.slots_received == 1 && service.probes_received == 1);
    assert(!bodaqs_record_queue_pop(&spi, record));
}

int main()
{
    test_whole_records_survive_overflow_and_wrap();
    test_queued_bootstrap_is_deferred_and_preserves_response();
}
