// Actual production reception builder and encoded CRC/ACK path; no fake throughput.
#include "bodaqs_master_service.h"
#include "bodaqs_batch_diagnostics.h"
#include <cassert>
#include <cstdio>
#include <cstring>
BodaqsBatchDiagnostics gMasterBatchInfo;
static BodaqsMasterService master;
static unsigned wire_hash=2166136261U;
static BodaqsMeasurementSlot transfer(BodaqsMeasurementSlot request,uint32_t now) {
    uint8_t wire[256],reply[256];BodaqsMeasurementSlot out={};
    assert(bodaqs_measurement_encode(&request,wire,256));
    const auto result=bodaqs_master_service_process_transfer(&master,wire,256,now,reply);
    if(result) std::fprintf(stderr,"transfer failure kind=%u at=%u result=%u\n",request.kind,now,result);
    assert(result==0);
    for(auto byte:reply) wire_hash=(wire_hash^byte)*16777619U;
    assert(bodaqs_measurement_decode(reply,256,&out));return out;
}
static void reset(uint32_t context=9) {
    bodaqs_master_service_init(&master,nullptr);
    bodaqs_control_exchange_init(&master.control,99);
    master.measurement.mode.phase=2;master.measurement.mode.context=context;
    master.measurement.mode.session=1;master.measurement.mode.recording=77;
    BodaqsMeasurementSlot idle={};idle.node=255;idle.context=context;transfer(idle,0);
    for(unsigned n=0;n<4;++n) {
        master.discovery[n].flags=1;master.discovery[n].boot_id=5;
        master.acquisition_record[n]=77;master.acquisition_boot[n]=5;
        master.anchor_boot[n]=5;master.anchor_epoch[n]=1;
    }
}
static bool sample(uint32_t now,unsigned n=0) {
    uint8_t p[64]={0,0,1,5};
    return bodaqs_master_service_receive_can(&master,n,1,0x100+n*8,p,64,0,now*1000U,now);
}
static void snapshot(uint32_t now,unsigned n=0) {
    uint8_t p[8]={1,0x23,1};
    assert(bodaqs_master_service_receive_can(&master,n,2,0x90+n,p,8,0,now*1000U,now));
}
static void consume(uint32_t start,uint32_t ack_at,bool combined=false,unsigned n=0) {
    const auto head=master.receptions[n].object;
    BodaqsMeasurementSlot poll={};poll.kind=1;poll.context=head.context;
    poll.node=n;poll.body[0]=head.cls;poll.object=head.object;
    BodaqsFragmentState assembled={};uint8_t bytes[1024]={};BodaqsMeasurementSlot ack={};
    for(unsigned i=0;i<(head.total+215U)/216U;++i) {
        poll.index=i;auto reply=transfer(poll,start+i);
        assert(bodaqs_fragment_accept(&assembled,bytes,sizeof bytes,&reply,1,&ack)>=0);
        // Delayed/repeated request must not count as new fragment progress.
        const auto duplicate=transfer(poll,start+i);
        assert(!std::memcmp(reply.body,duplicate.body,216));
    }
    assert(assembled.complete);
    auto wrong=ack;wrong.body[4]^=1;assert(transfer(wrong,ack_at).kind==7);
    assert(master.receptions[n].object.complete);
    if(combined) {ack.kind=14;ack.body[2]=1;ack.body[3]=n;}
    transfer(ack,ack_at); // Duplicate ACK below must not count retirement twice.
    transfer(ack,ack_at+1);
}
static void print(const char* name) {
    unsigned samples=0,evidence=0;
    for(unsigned n=0;n<4;++n) {samples+=master.ingress[n].count;evidence+=master.receptions[n].count;}
    std::printf("%s wire_hash=%u queued=%u head_records=%u\n",name,wire_hash,samples,evidence);
}
int main(int argc,char** argv) {
#if !BODAQS_MASTER_BATCH_DIAGNOSTICS
    (void)argc;(void)argv;
#endif
    reset();for(unsigned i=0;i<13;++i) assert(sample(i));
    assert(master.receptions[0].object.total==1008);
    consume(20,40);
#if BODAQS_MASTER_BATCH_DIAGNOSTICS
    auto d=gMasterBatchInfo.node[0];
    assert(d.sealed[0]==1 && d.retired[0]==1 && d.records[0][13]==1 && d.reasons[0][0]==1);
    assert(d.fresh_preparations[0]==5 && d.repeat_preparations[0]==5);
    assert(d.residence_total_ms[0]==28 && d.prepared_to_ack_total_ms[0]==16);
    if(argc>1) {
        FILE* f=std::fopen(argv[1],"wb");assert(f);
        assert(std::fwrite(&gMasterBatchInfo,1,sizeof gMasterBatchInfo,f)==sizeof gMasterBatchInfo);
        assert(!std::fclose(f));
    }
#endif
    print("full-and-duplicate-proof");
    // Holes in receive time: arrival services an already-expired partial head.
    reset();for(unsigned i=0;i<7;++i) assert(sample(i*3));assert(sample(21));
#if BODAQS_MASTER_BATCH_DIAGNOSTICS
    assert(gMasterBatchInfo.node[0].reasons[0][4]==1);
    assert(gMasterBatchInfo.node[0].records[0][7]==1);
#endif
    assert(master.receptions[0].count==7);consume(30,45,true);
    print("sparse-arrivals");
    reset();snapshot(0);for(unsigned i=0;i<8;++i) assert(sample(i*3));
    consume(24,30);
    assert(master.receptions[0].count==7);
#if BODAQS_MASTER_BATCH_DIAGNOSTICS
    assert(gMasterBatchInfo.node[0].reasons[0][3]==1);
#endif
    print("queued-reception-span");
    // Existing age rule seals a single old reception, even with queued backlog.
    reset();snapshot(0);for(unsigned i=0;i<30;++i) assert(sample(1+i));
    consume(32,40);
    assert(master.receptions[0].count==13);
    consume(41,55);
    print("head-retirement-backlog");
    // An evidence reception splits an otherwise full-capable sample batch.
    reset();for(unsigned i=0;i<6;++i) assert(sample(i));snapshot(6);
#if BODAQS_MASTER_BATCH_DIAGNOSTICS
    assert(gMasterBatchInfo.node[0].reasons[0][1]==1);
    assert(gMasterBatchInfo.node[0].records[0][6]==1);
#endif
    consume(7,12);consume(13,15);print("class-interleave");
    // Expired partial fill, clock wrap, independent node and recording reset.
    reset();assert(sample(0xfffffff0U,3));
    BodaqsMeasurementSlot poll={};poll.kind=1;poll.context=9;poll.node=3;poll.body[0]=1;
    transfer(poll,5);assert(master.receptions[3].object.complete);
#if BODAQS_MASTER_BATCH_DIAGNOSTICS
    assert(gMasterBatchInfo.node[3].seal_age_total_ms[0]==21);
    assert(gMasterBatchInfo.node[3].reasons[0][4]==1);
    assert(!gMasterBatchInfo.node[0].sealed[0]);
#endif
    print("wrap-and-node-isolation");reset(10);
#if BODAQS_MASTER_BATCH_DIAGNOSTICS
    assert(gMasterBatchInfo.context_lo==10 && !gMasterBatchInfo.node[3].sealed[0]);
#endif
    print("scope-reset");
    assert(sample(0,2));snapshot(1,2);master.acquisition_fenced=15;
    bodaqs_master_service_measurement_fence(&master,true,true);
#if BODAQS_MASTER_BATCH_DIAGNOSTICS
    assert(gMasterBatchInfo.node[2].discarded[0]==1);
    assert(gMasterBatchInfo.node[2].retired[0]==0);
#endif
    print("fence-discard");
}
