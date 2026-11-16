#include "bodaqs_master_service.h"
#include <cassert>
#include <cstdio>
#include <cstring>
static BodaqsMasterService master;
static BodaqsMasterWindowStorage window;
static unsigned essentialLost=0,optionalLost=0,retired=0,peak=0;
static BodaqsMeasurementSlot exchange(const BodaqsMeasurementSlot& request,unsigned now) {
    uint8_t tx[BODAQS_MEASUREMENT_BYTES],rx[BODAQS_MEASUREMENT_BYTES];
    BodaqsMeasurementSlot reply={};
    assert(bodaqs_measurement_encode_request(&request,tx,sizeof tx));
    assert(bodaqs_master_service_process_transfer(&master,tx,sizeof tx,now,rx)==0);
    assert(bodaqs_measurement_decode(rx,sizeof rx,&reply));return reply;
}
static void send(unsigned n,bool optional,unsigned now) {
    uint8_t p[64]={1,0x24,1,0,0,0,56};unsigned length=64;
    if(!optional) {
        memset(p,0,sizeof p);p[0]=1;p[1]=0x22;p[2]=1;p[6]=20;p[9]=1;p[10]=1;p[24]=1;
        bodaqs_measurement_put(p+12,now*3,4);bodaqs_measurement_put(p+16,now*1000,4);
        bodaqs_measurement_put(p+20,300,4);length=32;
    }
    const bool accepted=bodaqs_master_service_receive_can(&master,n,2,0x90+n,p,length,0,now*1000,now);
    if(!accepted){if(optional)++optionalLost;else ++essentialLost;}
    if(window.evidence_count[n]>peak)peak=window.evidence_count[n];
}
int main(int argc,char** argv) {
    assert(argc==2);
    bodaqs_master_service_init(&master,nullptr);assert(bodaqs_master_service_bind_window(&master,&window));
    master.measurement.mode.phase=2;master.measurement.mode.context=9;master.measurement.mode.session=1;master.measurement.mode.recording=77;
    BodaqsMeasurementSlot poll={};poll.kind=1;poll.context=9;poll.node=0;poll.body[0]=2;exchange(poll,0);
    for(unsigned n=0;n<4;++n){master.discovery[n].flags=1;master.discovery[n].boot_id=5+n;master.acquisition_record[n]=77;master.acquisition_boot[n]=5+n;}
    if(std::strcmp(argv[1],"burst")==0) {
        // Synthetic retained optional backlog followed by eight valid essential
        // anchors. This checks a declared burst envelope, not r31 chronology.
        for(unsigned n=0;n<4;++n) {
            for(unsigned i=0;i<32;++i)send(n,true,1);
            for(unsigned i=0;i<8;++i)send(n,false,2+i);
        }
        printf("burst reserve=%u optional_dropped=%u essential_dropped=%u peak=%u\n",BODAQS_ESSENTIAL_RESERVE,optionalLost,essentialLost,peak);
        fflush(stdout);assert(essentialLost==0);return 0;
    }
    // Four nodes emit model+snapshot+anchor every100ms (120 evidence frames/s).
    // Model-only optional payloads exercise admission/classification, not node
    // interpretation. Independent 20 heads/s/node drain has 2x essential demand.
    for(unsigned ms=0;ms<10000;++ms) {
        if(ms%100==0)for(unsigned n=0;n<4;++n){send(n,true,ms);send(n,true,ms);send(n,false,ms);}
        if(ms%50==25)for(unsigned n=0;n<4;++n){
            auto& batch=master.receptions[n];
            if(!batch.object.complete)continue;
            BodaqsMeasurementSlot fragment={},ack={};BodaqsFragmentState received={};uint8_t data[1024]={};
            assert(bodaqs_fragment_emit(&batch.object,batch.bytes,0,&fragment));
            assert(bodaqs_fragment_accept(&received,data,sizeof data,&fragment,1,&ack)==1);
            ack.kind=14;ack.body[2]=2;ack.body[3]=n;
            auto response=exchange(ack,ms);assert(response.retired && response.retiredObject==ack.object);++retired;
        }
    }
    printf("reserve=%u optional_dropped=%u essential_dropped=%u retired=%u peak=%u failed=%u,%u,%u,%u\n",
        BODAQS_ESSENTIAL_RESERVE,optionalLost,essentialLost,retired,peak,
        master.loss[0].failed,master.loss[1].failed,master.loss[2].failed,master.loss[3].failed);
    assert(optionalLost>0);assert(essentialLost==0);
    for(auto& loss:master.loss)assert(!loss.failed);
}
