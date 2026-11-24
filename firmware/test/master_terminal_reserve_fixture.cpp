#include "bodaqs_master_service.h"
#include <cassert>
#include <cstdio>
#include <cstring>
static BodaqsMasterService master;
static BodaqsMeasurementSlot transfer(BodaqsMeasurementSlot request,unsigned now) {
    uint8_t wire[256],reply[256];BodaqsMeasurementSlot out={};
    assert(bodaqs_measurement_encode(&request,wire,256));
    assert(bodaqs_master_service_process_transfer(&master,wire,256,now,reply)==0);
    assert(bodaqs_measurement_decode(reply,256,&out));return out;
}
static void boundary(uint8_t* p,uint8_t kind,unsigned sequence) {
    memset(p,0,64);p[0]=1;p[1]=0x25;p[2]=1;p[6]=56;
    bodaqs_measurement_put(p+8,5,4);p[13]=1;p[14]=kind;p[15]=2;
    bodaqs_measurement_put(p+16,kind,4);bodaqs_measurement_put(p+28,sequence,4);
    bodaqs_measurement_put(p+54,kind==2?0x161:0x261,2);
}
int main(int argc,char** argv) {
    bodaqs_master_service_init(&master,nullptr);
    bodaqs_control_exchange_init(&master.control,99);
    master.measurement.mode.phase=2;master.measurement.mode.context=9;
    master.measurement.mode.session=1;master.measurement.mode.recording=77;
    BodaqsMeasurementSlot idle={};idle.node=255;idle.context=9;
    transfer(idle,0); // establish the real transfer scope before seeding ownership
    master.discovery[0].flags=1;master.discovery[0].boot_id=5;
    master.acquisition_record[0]=77;master.acquisition_boot[0]=5;
    uint8_t start[64];boundary(start,2,0);
    assert(bodaqs_master_service_receive_can(&master,0,2,0x90,start,64,0,1,1));
    const BodaqsReceptionBatch pinned=master.receptions[0];
    assert(pinned.object.complete);
    for(unsigned i=0;i<128;++i) {
        uint8_t packet[64]={0,0,1,5};bodaqs_measurement_put(packet,i*5,2);
        (void)bodaqs_master_service_receive_can(&master,0,1,0x100,packet,64,0,2+i,2);
    }
    uint8_t stop[64];boundary(stop,8,639);
    if(argc>1 && (!strcmp(argv[1],"malformed") || !strcmp(argv[1],"transaction-low") || !strcmp(argv[1],"transaction-high"))) {
        if(!strcmp(argv[1],"malformed")) stop[2]=2;
        else stop[!strcmp(argv[1],"transaction-low")?4:5]=1;
        assert(!bodaqs_master_service_receive_can(&master,0,2,0x90,stop,64,0,200,3));
        assert(master.ingress[0].count==126);
        puts("Malformed terminal envelope cannot consume the boundary reserve: PASS");
        return 0;
    }
    // Goes red on the original queue: final interpretation metadata is lost,
    // failed latches, and subsequent polling reports reason14 instead of STOP.
    assert(bodaqs_master_service_receive_can(&master,0,2,0x90,stop,64,0,200,3));
    assert(!master.loss[0].failed && master.ingress[0].count<=128);
    assert(master.ingress[0].dropped>0 && master.loss[0].source>0);
    if(argc>1 && !strcmp(argv[1],"exhaustion")) {
        assert(bodaqs_master_service_receive_can(&master,0,2,0x90,stop,64,0,201,3));
        assert(master.ingress[0].count==128);
        assert(!bodaqs_master_service_receive_can(&master,0,2,0x90,stop,64,0,202,3));
        assert(master.loss[0].failed);
        puts("Exhausted terminal reserve keeps the existing explicit fatal-loss behavior: PASS");
        return 0;
    }
    assert(!memcmp(&pinned,&master.receptions[0],sizeof pinned));
    unsigned records=0;bool sawStop=false;uint64_t ordinal=0;
    for(unsigned turns=0;turns<200 && !sawStop;++turns) {
        const auto cls=master.receptions[0].cls;
        BodaqsMeasurementSlot poll={};poll.kind=1;poll.context=9;poll.node=0;poll.body[0]=cls;
        auto first=transfer(poll,30);
        assert(first.kind==bodaqs_fragment_kind(cls));
        BodaqsFragmentState assembled={};uint8_t bytes[1024]={};BodaqsMeasurementSlot ack={};
        for(unsigned i=0;i<(first.total+215U)/216U;++i) {
            poll.object=first.object;poll.index=i;
            auto fragment=transfer(poll,30);
            assert(bodaqs_fragment_accept(&assembled,bytes,sizeof bytes,&fragment,1,&ack)>=0);
        }
        assert(assembled.complete);
        for(unsigned i=0;i<bodaqs_measurement_get(bytes+12,2);++i) {
            const uint8_t* row=bytes+16+76*i;
            const uint64_t order=(bodaqs_measurement_get(bytes+8,4)<<32)|bodaqs_measurement_get(row+8,4);
            assert(order>ordinal);ordinal=order;++records;
            if(cls==2 && row[13]==0x25 && row[26]==8) {
                assert(bodaqs_measurement_get(row+40,4)==639);
                sawStop=true;
            }
        }
        transfer(ack,30); // exact canonical CRC/identity proof, never synthetic retirement
    }
    assert(sawStop && records>2 && !master.loss[0].failed);
    puts("Full master ingress retains and drains the real final boundary in FIFO order: PASS");
}
