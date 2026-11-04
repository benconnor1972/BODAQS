#include <assert.h>
#include <string.h>
#include "bodaqs_measurement.h"
static void transitions();
int main() {
    transitions();
    BodaqsMeasurementSlot slot = {};
    uint8_t wire[64];
    slot.kind = 6; slot.context = 0x0807060504030201ULL;
    slot.object = 0x11223344; slot.node = 255;
    assert(bodaqs_measurement_encode(&slot, wire, sizeof wire));
    assert(wire[0] == 'B' && wire[1] == 'M' && wire[2] == 1 && wire[3] == 6);
    assert(wire[4] == 1 && wire[11] == 8 && wire[12] == 0x44 && wire[15] == 0x11);
    // Independent Python zlib CRC-32/ISO-HDLC vector for the declared bytes.
    assert(wire[60]==0x44 && wire[61]==0x5f && wire[62]==0xd4 && wire[63]==0x25);
    BodaqsMeasurementSlot decoded = {};
    assert(bodaqs_measurement_decode(wire, 64, &decoded));
    assert(decoded.context == 0x0807060504030201ULL);
    assert(!bodaqs_measurement_decode(wire, 63, &decoded));
    wire[31] ^= 1;
    assert(!bodaqs_measurement_decode(wire, 64, &decoded));
}
#include "bodaqs_master_service.h"
#include "CanMasterProtocol.h"
static void transitions() {
    BodaqsMasterService master = {};
    bodaqs_master_service_init(&master, nullptr);
    bodaqs_control_exchange_init(&master.control, 7);
    BodaqsMeasurementMode mode = {};
    mode.boot=7; mode.session=11; mode.caller=11; mode.recording=19; mode.context=23;
    mode.version=1; mode.maximum=1024; mode.physical=64; mode.hz=8000000; mode.gap=25;
    CanMasterProtocol::Frame request;
    request.type=static_cast<CanMasterProtocol::MessageType>(8);
    request.sequence=41; request.payloadLength=64;
    bodaqs_measurement_mode_encode(&mode,request.payload);
    uint8_t tx[84],rx[84];
    assert(CanMasterProtocol::encodeSlot(request,tx,sizeof tx));
    assert(bodaqs_master_service_process_transfer(&master,tx,84,100,rx)==BODAQS_MASTER_SLOT_PROCESSED);
    assert(master.measurement.mode.phase==1);
    assert(bodaqs_master_service_process_transfer(&master,tx,63,200,rx)==BODAQS_MASTER_SLOT_MALFORMED);
    assert(master.measurement.mode.phase==1);
    assert(bodaqs_master_service_process_transfer(&master,tx,84,900,rx)==BODAQS_MASTER_SLOT_PROCESSED);
    BodaqsMeasurementSlot confirm = {}; confirm.kind=8; confirm.node=255; confirm.object=41; confirm.context=23;
    bodaqs_measurement_confirm_body(&mode,confirm.body);
    assert(bodaqs_measurement_encode(&confirm,tx,64));
    assert(bodaqs_master_service_process_transfer(&master,tx,64,950,rx)==BODAQS_MASTER_SLOT_PROCESSED);
    assert(master.measurement.mode.phase==2);
    assert(bodaqs_master_service_process_transfer(&master,tx,64,1200,rx)==BODAQS_MASTER_SLOT_PROCESSED);
    BodaqsMeasurementSlot status = {};
    assert(bodaqs_measurement_decode(rx,64,&status));
    assert(status.body[32]==2 && status.object==41);
    confirm.context=24; bodaqs_measurement_encode(&confirm,tx,64);
    assert(bodaqs_master_service_process_transfer(&master,tx,64,1300,rx)==BODAQS_MASTER_SLOT_MALFORMED);
    confirm.kind=6; confirm.object=99; memset(confirm.body,0,40);
    bodaqs_measurement_encode(&confirm,tx,64);
    assert(bodaqs_master_service_process_transfer(&master,tx,64,1400,rx)==BODAQS_MASTER_SLOT_PROCESSED);
    assert(master.measurement.mode.context==23 && master.measurement.mode.phase==2);
    assert(bodaqs_measurement_decode(rx,64,&status));
    assert(status.context==24 && status.object==99 && bodaqs_measurement_get(status.body+24,8)==23);
    // Timed-out entry retains identity; retries cannot restart its one-second deadline.
    BodaqsMeasurementState pending = {}; pending.mode.boot=7; pending.quiescent=true; pending.fenced=true;
    assert(bodaqs_measurement_stage(&pending,&mode,51,10,false)==0);
    assert(bodaqs_measurement_stage(&pending,&mode,51,999,false)==0);
    assert(bodaqs_measurement_stage(&pending,&mode,51,1010,false)==12);
    assert(pending.mode.phase==4);
    BodaqsMeasurementState exiting = {}; exiting.mode=mode; exiting.mode.phase=2;
    exiting.quiescent=true; exiting.fenced=true;
    BodaqsMeasurementMode closure=mode; closure.phase=3;
    assert(bodaqs_measurement_stage(&exiting,&closure,52,10,true)==0);
    assert(bodaqs_measurement_stage(&exiting,&closure,52,999,true)==0);
    assert(bodaqs_measurement_stage(&exiting,&closure,52,1010,true)==12);
    assert(exiting.mode.phase==4 && exiting.mode.context==23);
    // A fresh read-only legacy MODE_INFO remains usable after entering 64-byte mode.
    request.type=static_cast<CanMasterProtocol::MessageType>(10); request.sequence=42; request.payloadLength=16;
    memset(request.payload,0,64); request.payload[0]=57; request.payload[8]=7;
    CanMasterProtocol::encodeSlot(request,tx,sizeof tx);
    assert(bodaqs_master_service_process_transfer(&master,tx,84,1500,rx)==BODAQS_MASTER_SLOT_PROCESSED);
    CanMasterProtocol::Frame observed;
    assert(CanMasterProtocol::decodeSlot(rx,84,observed)==CanMasterProtocol::DecodeResult::Ok);
    assert(static_cast<unsigned>(observed.type)==0x8a && observed.payload[48]==57 && observed.payload[38]==2);
    assert(master.measurement.mode.context==23);
    BodaqsMeasurementMode invalid=mode; invalid.boot=8;
    assert(bodaqs_measurement_stage(&master.measurement,&invalid,43,1500,false)==4);
    invalid=mode; invalid.maximum=1000;
    assert(bodaqs_measurement_stage(&master.measurement,&invalid,43,1500,false)==13);
    mode.phase=3;
    bodaqs_master_service_measurement_fence(&master,false,false);
    assert(bodaqs_measurement_stage(&master.measurement,&mode,44,1600,true)==10);
    bodaqs_master_service_measurement_fence(&master,true,true);
    assert(bodaqs_measurement_stage(&master.measurement,&mode,44,1600,true)==0);
    confirm.kind=9; confirm.context=23; confirm.object=44;
    bodaqs_measurement_confirm_body(&mode,confirm.body);
    bodaqs_measurement_encode(&confirm,tx,64);
    assert(bodaqs_master_service_process_transfer(&master,tx,64,1700,rx)==BODAQS_MASTER_SLOT_PROCESSED);
    assert(master.measurement.mode.phase==0);
    assert(bodaqs_master_service_process_transfer(&master,tx,64,1800,rx)==BODAQS_MASTER_SLOT_PROCESSED);
}
