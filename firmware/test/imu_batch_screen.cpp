// Real master wire/retention/ACK code with synthetic arrivals and a simple reader.
// No DMA, RTOS, SD or CAN arbitration model; never a hardware capacity result.
#include "bodaqs_master_service.h"
#include <cassert>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <cstdlib>

static BodaqsMasterService service;
static unsigned profileCalls;
extern "C" uint32_t bodaqs_master_profile_clock(void) {
    return static_cast<uint32_t>(std::chrono::duration_cast<std::chrono::microseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count());
}
extern "C" void bodaqs_master_profile_record(uint32_t,uint32_t,uint32_t,uint8_t,uint8_t) {
    ++profileCalls;
}
static BodaqsMeasurementSlot transfer(const BodaqsMeasurementSlot& request,unsigned now) {
    uint8_t tx[256],rx[256]; BodaqsMeasurementSlot reply={};
    assert(bodaqs_measurement_encode(&request,tx,sizeof tx));
    assert(bodaqs_master_service_process_transfer(&service,tx,sizeof tx,now,rx)==BODAQS_MASTER_SLOT_PROCESSED);
    assert(bodaqs_measurement_decode(rx,sizeof rx,&reply));
    return reply;
}
static void init() {
    BodaqsMasterIdentity identity={}; bodaqs_master_service_init(&service,&identity);
    bodaqs_control_exchange_init(&service.control,99);service.measurement.mode.boot=99;
    BodaqsMeasurementMode mode={};mode.boot=99;mode.session=1;mode.recording=77;
    mode.context=9;mode.caller=1;mode.version=2;mode.maximum=1024;
    mode.physical=256;mode.hz=16000000;mode.gap=25;
    assert(!bodaqs_measurement_stage(&service.measurement,&mode,7,1,false));
    BodaqsMeasurementSlot confirm={};confirm.kind=8;confirm.node=255;confirm.context=9;confirm.object=7;
    bodaqs_measurement_confirm_body(&mode,confirm.body);assert(transfer(confirm,100).body[32]==2);
    BodaqsMeasurementSlot warm={};warm.kind=1;warm.context=9;warm.node=0;warm.body[0]=1;
    (void)transfer(warm,100); // establish transfer scope before seeding ownership
    for(unsigned n=0;n<2;++n) {
        service.discovery[n].flags=1;service.discovery[n].boot_id=17+n;
        service.acquisition_record[n]=77;service.acquisition_boot[n]=17+n;
        // Seed ownership/anchor state explicitly; acquisition lifecycle is tested elsewhere.
        service.anchor_boot[n]=17+n;service.anchor_epoch[n]=1;
    }
}
int main(int argc,char**argv) {
    assert(argc==2);const unsigned ackDelay=static_cast<unsigned>(std::atoi(argv[1]));
    init();
    BodaqsFragmentState assemblies[2]={}; uint8_t buffers[2][1024]={};
    BodaqsMeasurementSlot acks[2]={};unsigned delays[2]={},next[2]={0,750};
    unsigned offered[2]={},accepted[2]={},objects[2]={},empty=0,repeats=0,requests=0;
    unsigned turn=0,lossReplies=0;
    for(unsigned us=0;us<2000000;us+=500) {
        const unsigned now=100+us/1000;
        for(unsigned n=0;n<2;++n) while(next[n]<=us) {
            uint8_t packet[64]={};const unsigned sequence=offered[n]*5;
            packet[0]=sequence;packet[1]=sequence>>8;packet[2]=1;packet[3]=5;
            (void)bodaqs_master_service_receive_can(&service,n,1,0x100+8*n,packet,64,0,us,now);
            ++offered[n];next[n]+=1500;
        }
        const unsigned node=(turn++)%2;
        BodaqsMeasurementSlot request={};request.kind=1;request.node=node;request.context=9;request.body[0]=1;
        auto& state=assemblies[node];
        if(state.complete && delays[node]++>=ackDelay) {
            request=acks[node];request.kind=14;request.body[2]=1;request.body[3]=node;
        } else if(state.object && !state.complete) {
            request.object=state.object;
            while(state.mask&(1u<<request.index)) ++request.index;
        }
        const auto reply=transfer(request,now);++requests;
        if(reply.retired && state.complete) { state={};delays[node]=0; }
        if(reply.kind==0) {++empty;continue;}
        if(reply.kind==7 && (reply.body[1]==9 || reply.body[1]==14)) {++lossReplies;continue;}
        assert(reply.kind==2 && reply.node==node);
        const int result=bodaqs_fragment_accept(&state,buffers[node],sizeof buffers[node],&reply,1,&acks[node]);
        assert(result>=0);
        if(result==1) {
            const unsigned count=bodaqs_measurement_get(buffers[node]+12,2);
            assert(count>0 && count<=13);accepted[node]+=count; ++objects[node];
        } else if(result==2) ++repeats;
    }
    assert(service.objects_acked<=objects[0]+objects[1]);
    // A nonempty retained head must not retire before its validated ACK.
    for(unsigned n=0;n<2;++n) assert(accepted[n]<=offered[n]);
    const auto began=std::chrono::steady_clock::now();
    BodaqsMeasurementSlot poll={};poll.kind=1;poll.context=9;poll.node=3;poll.body[0]=1;
    unsigned check=0;
    for(unsigned i=0;i<20000;++i) check+=transfer(poll,2100).kind;
    const auto ns=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-began).count();
    std::printf("{\"offered_packets\":[%u,%u],\"admitted_packets\":[%u,%u],\"objects\":[%u,%u],"
        "\"ingress_dropped\":[%u,%u],\"requests\":%u,\"empty\":%u,\"replays\":%u,"
        "\"loss_replies\":%u,\"profile_callbacks\":%u,\"host_roundtrip_ns\":%lld,\"check\":%u}\n",
        offered[0],offered[1],accepted[0],accepted[1],objects[0],objects[1],
        service.ingress[0].dropped,service.ingress[1].dropped,requests,empty,repeats,
        lossReplies,profileCalls,static_cast<long long>(ns/20000),check);
}
