#include "bodaqs_master_service.h"
#include <cassert>
#include <cstring>

static BodaqsMasterService master;
static void reset() {
    BodaqsMasterIdentity identity = {};
    bodaqs_master_service_init(&master, &identity);
    bodaqs_control_exchange_init(&master.control, 99);
    master.measurement.mode.phase = 2;
    master.measurement.mode.context = 9;
    master.measurement.mode.session = 1;
    master.measurement.mode.recording = 77;
    master.discovery[0].flags = 1;
    master.discovery[0].boot_id = 5;
    master.acquisition_record[0] = 77;
    master.acquisition_boot[0] = 5;
}
static BodaqsMeasurementSlot poll(unsigned cls, unsigned index, unsigned id, unsigned now) {
    BodaqsMeasurementSlot request = {}, reply = {};
    uint8_t wire[64], response[84];
    request.kind = 1; request.context = 9; request.node = 0;
    request.body[0] = cls; request.index = index; request.object = id;
    assert(bodaqs_measurement_encode(&request, wire, 64));
    assert(bodaqs_master_service_process_transfer(&master, wire, 64, now, response) == 0);
    assert(bodaqs_measurement_decode(response, 64, &reply));
    return reply;
}
static void acknowledge(unsigned cls, unsigned now) {
    BodaqsFragmentState assembled = {};
    BodaqsMeasurementSlot ack = {};
    uint8_t bytes[1024] = {}, wire[64], response[84];
    auto first = poll(cls, 0, 0, now);
    assert(first.kind == (cls == 1 ? 2 : 3));
    const unsigned fragments = (first.total + 39) / 40;
    for (unsigned i = 0; i < fragments; ++i) {
        auto fragment = poll(cls, i, first.object, now);
        assert(bodaqs_fragment_accept(&assembled, bytes, sizeof bytes, &fragment, 1, &ack)
            == (i + 1 == fragments ? 1 : 0));
    }
    assert(bodaqs_measurement_encode(&ack, wire, 64));
    assert(bodaqs_master_service_process_transfer(&master, wire, 64, now, response) == 0);
}
static void anchor(unsigned now) {
    // Literal version-1 STREAM_ANCHOR: epoch3, sequence0, tick100, step300/1.
    const uint8_t bytes[32] = {1,0x22,1,0,0,0,20,0,0,1,3,0,
        0,0,0,0,100,0,0,0,44,1,0,0,1,0,0,0,0,0,0,0};
    assert(bodaqs_master_service_receive_can(&master, 0, 2, 0x090, bytes, 32, 0, 1234, now));
}
static bool samples(unsigned sequence, unsigned now) {
    uint8_t bytes[64] = {0,0,3,5};
    bytes[0] = sequence; bytes[1] = sequence >> 8;
    bytes[4] = 0x34; bytes[5] = 0x12; bytes[6] = 0xff; bytes[7] = 0xff;
    return bodaqs_master_service_receive_can(&master, 0, 1, 0x100, bytes, 64, 0, 5678, now);
}
int main() {
    reset(); anchor(0);
    const auto pinned = poll(2, 0, 0, 0);
    assert(pinned.kind == 3 && pinned.total == 96); // Essential evidence never waits 20ms.
    for (unsigned i = 0; i < 96; ++i) assert(samples(i * 5, 1));
    assert(!samples(480, 1)); // Drop newest whole reception, preserve selected and queued data.
    const auto repeat = poll(2, 0, pinned.object, 19);
    assert(std::memcmp(&pinned, &repeat, sizeof pinned) == 0);
    assert(poll(1, 0, 0, 19).kind == 0); // Data cannot overtake its evidence head.
    acknowledge(2, 20);
    const auto data = poll(1, 0, 0, 20);
    assert(data.kind == 2 && data.total == 1008);
    assert(data.body[12] == 13 && data.body[16] == 0 && data.body[17] == 1);
    assert(data.body[18] == 64);
    assert(data.body[20] == 0x2e && data.body[21] == 0x16); // ISR receive tick5678 preserved.
    assert(data.body[32] == 0x34 && data.body[33] == 0x12 && data.body[34] == 0xff);
    // Partial fill uses original ingress age even when an older head delayed selection.
    reset(); anchor(0); assert(samples(0, 1)); assert(samples(5, 49)); acknowledge(2, 50);
    assert(poll(1, 0, 0, 50).total == 96);
    // Undiscovered, foreign-record and rebooted senders cannot enter retained state.
    reset(); master.acquisition_record[0] = 78;
    const uint8_t event[8] = {};
    assert(!bodaqs_master_service_receive_can(&master, 0, 2, 0x060, event, 8, 0, 1, 0));
    master.acquisition_record[0] = 77; master.discovery[0].boot_id = 6;
    assert(!bodaqs_master_service_receive_can(&master, 0, 2, 0x060, event, 8, 0, 1, 0));
    // Ordinary reception-ordinal wrap changes only the batch high part.
    reset(); master.reception_ordinal = 0xfffffffeULL; anchor(0);
    assert(samples(0, 1)); acknowledge(2, 21);
    const auto wrapped = poll(1, 0, 0, 21);
    assert(wrapped.body[8] == 1 && wrapped.body[24] == 0 && wrapped.body[25] == 0);
    // A real completed FENCE reply retires both pinned and queued old receptions.
    reset(); anchor(0); assert(samples(0, 1));
    BodaqsControlWrapped request = {};
    request.master_boot_id = 99; request.node_address = 0;
    request.record.opcode = BODAQS_CONTROL_FENCE_OLD_DATA;
    request.record.endpoint = 255; request.record.node_boot_id = 5;
    request.record.operation = 11; request.record.session = 1;
    request.record.data_length = 24; request.record.data[0] = 77;
    uint8_t content[68] = {}, wire[64], response[84], can[64];
    BodaqsFragmentState object = {};
    assert(bodaqs_control_encode_wrapped(&request, content));
    assert(bodaqs_fragment_seal(&object, content, 68, 9, 1, 0, 3, 0, 64));
    for (unsigned index = 0; index < 2; ++index) {
        BodaqsMeasurementSlot fragment = {};
        assert(bodaqs_fragment_emit(&object, content, index, &fragment));
        assert(bodaqs_measurement_encode(&fragment, wire, 64));
        assert(bodaqs_master_service_process_transfer(&master, wire, 64, 30, response) == 0);
    }
    uint8_t address; uint16_t transaction;
    assert(bodaqs_master_service_control_transmit(&master, 30, &address, &transaction, can));
    BodaqsControlRecord result = request.record;
    std::memset(result.data, 0, 24); result.data[0] = 3; result.data[3] = BODAQS_CONTROL_FENCE_OLD_DATA;
    result.data[4] = 11;
    assert(bodaqs_master_service_control_receive(&master, 0, transaction, &result));
    assert(master.retired_tail_frames == 2);
    assert(poll(2, 0, 0, 31).kind == 0 && !samples(5, 32));
    // Exhaustion cannot wrap an object identity or append beyond a full head.
    reset(); anchor(0); acknowledge(2, 0);
    master.receptions[0].next_id[0] = UINT32_MAX;
    for (unsigned i = 0; i < 20; ++i) assert(samples(i * 5, 1));
    const auto exhausted = poll(1, 0, 0, 21);
    assert(exhausted.kind == 7 && exhausted.body[1] == 9);
    // A restarted logger may reuse a numeric context only under a new bound
    // session after fencing. Old retained fragments and ACK caches then retire.
    reset();anchor(0);
    const auto oldPinned=master.receptions[0].object;
    master.acquisition_fenced=1;
    master.measurement.mode.session=2;
    assert(poll(2,0,0,1).kind==0);
    BodaqsMeasurementSlot staleAck={},staleReply={};
    bodaqs_fragment_ack(&oldPinned,1,&staleAck);
    assert(bodaqs_measurement_encode(&staleAck,wire,64));
    assert(bodaqs_master_service_process_transfer(&master,wire,64,2,response)==0);
    assert(bodaqs_measurement_decode(response,64,&staleReply));
    assert(staleReply.kind==7 && staleReply.body[1]==5);
}
