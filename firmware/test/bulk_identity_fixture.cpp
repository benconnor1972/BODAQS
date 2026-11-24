#include "bodaqs_master_service.h"
#include "CanMasterManager.h"
#include <cassert>
#include <cstdio>
static BodaqsMasterService master;
static BodaqsMasterWindowStorage window;
static BodaqsMeasurementSlot exchange(const BodaqsMeasurementSlot& request) {
    uint8_t tx[BODAQS_MEASUREMENT_BYTES]={},rx[BODAQS_MEASUREMENT_BYTES];
    BodaqsMeasurementSlot response={};
    assert(bodaqs_measurement_encode_request(&request,tx,sizeof tx));
    assert(bodaqs_master_service_process_transfer(&master,tx,sizeof tx,30,rx)==0);
    assert(bodaqs_measurement_decode(rx,sizeof rx,&response));return response;
}
static void reset(uint64_t context) {
    bodaqs_master_service_init(&master,nullptr);
    assert(bodaqs_master_service_bind_window(&master,&window));
    bodaqs_control_exchange_init(&master.control,99);
    master.measurement.mode.phase=2;master.measurement.mode.context=context;
    master.measurement.mode.session=1;master.measurement.mode.recording=77;
    BodaqsMeasurementSlot idle={};idle.context=context;idle.node=255;exchange(idle);
    master.discovery[0].flags=1;master.discovery[0].boot_id=5;
    master.acquisition_record[0]=77;master.acquisition_boot[0]=5;
    master.anchor_boot[0]=5;master.anchor_epoch[0]=1;
}
int main() {
    reset(9);
    master.receptions[0].next_id[0]=UINT32_MAX-BODAQS_SAMPLE_WINDOW;
    uint8_t can[64]={0,0,1,5};
    for(unsigned i=0;i<BODAQS_SAMPLE_PAYLOADS;++i)
        (void)bodaqs_master_service_receive_can(&master,0,1,0x100,can,64,0,1,1);
    BodaqsMeasurementSlot ready={};ready.kind=15;ready.node=255;ready.context=9;
    bodaqs_measurement_put(ready.body,UINT32_MAX-BODAQS_SAMPLE_WINDOW,4);
    assert(exchange(ready).kind!=2);
    assert(master.loss[0].failed && master.receptions[0].next_id[0]==UINT32_MAX-BODAQS_SAMPLE_WINDOW);
    reset(10);
    master.receptions[0].next_id[1]=UINT32_MAX;
    uint8_t anchor[32]={1,0x22,1,0,0,0,20,0,0,1,1};anchor[24]=1;
    (void)bodaqs_master_service_receive_can(&master,0,2,0x90,anchor,32,0,1,1);
    BodaqsMeasurementSlot poll={};poll.kind=1;poll.context=10;poll.node=0;poll.body[0]=2;
    assert(exchange(poll).kind!=3);
    assert(master.loss[0].failed && master.receptions[0].next_id[1]==UINT32_MAX);
    // Compact ACK retains every byte of the exhausted predecessor identity.
    CanMasterManager::MeasurementInbox inbox;
    inbox.state.context=10;inbox.state.object=UINT32_MAX-5;inbox.state.node=0;
    inbox.state.cls=1;inbox.state.total=BODAQS_SAMPLE_UNIT_MAX;inbox.state.checksum=0x11223344;
    CanMasterManager::rememberMeasurementAcknowledgement(inbox);
    BodaqsMeasurementSlot old=inbox.pendingAck;
    assert(old.kind==5 && old.object==UINT32_MAX-5 && old.total==BODAQS_SAMPLE_UNIT_MAX);
    assert(bodaqs_measurement_get(old.body+4,4)==0x11223344);
    reset(11); // only a new measurement context may restart object allocation
    assert(!master.receptions[0].next_id[0] && !master.loss[0].failed);
    const auto rejected=exchange(old);
    assert(!rejected.retired && master.receptions[0].next_id[0]==0);
    assert(old.context==10 && old.object==UINT32_MAX-5);
    puts("bulk sample/evidence exhaustion, compact predecessor ACK and stale-context restart: PASS");
}
