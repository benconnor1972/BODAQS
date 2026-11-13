#include "bodaqs_master_service.h"
#include "RemoteImuStream.h"
#include "BdqV2Writer.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <vector>
static BodaqsMasterService master;
static BodaqsMasterWindowStorage storage;
static BodaqsMeasurementSlot ramAck(const BodaqsMeasurementSlot& unit);
static BodaqsMeasurementSlot exchange(const BodaqsMeasurementSlot& r,unsigned now=30) {
    uint8_t wire[256],reply[256];BodaqsMeasurementSlot out={};
    assert(bodaqs_measurement_encode(&r,wire,256));
    assert(bodaqs_master_service_process_transfer(&master,wire,256,now,reply)==0);
    assert(bodaqs_measurement_decode(reply,256,&out));return out;
}
static BodaqsMeasurementSlot ready(unsigned nodes=4) {
    BodaqsMeasurementSlot r={};r.kind=15;r.context=9;r.node=255;
    for(unsigned n=0;n<nodes;++n) bodaqs_measurement_put(r.body+8*n,1,4);
    return r;
}
static void reset() {
    bodaqs_master_service_init(&master,nullptr);
    assert(bodaqs_master_service_bind_window(&master,&storage));
    bodaqs_control_exchange_init(&master.control,99);
    master.measurement.mode.phase=2;master.measurement.mode.context=9;
    master.measurement.mode.session=1;master.measurement.mode.recording=77;
    BodaqsMeasurementSlot poll={};poll.kind=1;poll.context=9;poll.node=0;poll.body[0]=2;
    exchange(poll);
    for(unsigned n=0;n<4;++n) {
        master.discovery[n].flags=1;master.discovery[n].boot_id=5+n;
        master.acquisition_record[n]=77;master.acquisition_boot[n]=5+n;
        uint8_t start[64]={1,0x25,1,0,0,0,56};start[13]=1;start[14]=2;
        bodaqs_measurement_put(start+8,5+n,4);bodaqs_measurement_put(start+54,0x161,2);
        assert(bodaqs_master_service_receive_can(&master,n,2,0x90+n,start,64,0,1,1));
        uint8_t anchor[32]={1,0x22,1,0,0,0,20,0,0,1,1};anchor[24]=1;
        bodaqs_measurement_put(anchor+16,100,4);bodaqs_measurement_put(anchor+20,300,4);
        assert(bodaqs_master_service_receive_can(&master,n,2,0x90+n,anchor,32,0,1,1));
    }
}
static void recordFour(const char* path,BodaqsMeasurementSlot units[4][4]) {
    RemoteImuStream streams[4];
    auto evidence=[&](unsigned n) {
        for(unsigned i=0;i<4;++i) {
            BodaqsMeasurementSlot poll={};poll.kind=1;poll.context=9;poll.node=n;poll.body[0]=2;
            auto out=exchange(poll);if(!out.kind) break;assert(out.kind==3);
            const auto* r=out.body+16;
            assert(streams[n].accept((uint16_t)bodaqs_measurement_get(r,2),r+12,r[2],
                (uint32_t)bodaqs_measurement_get(r+4,4),bodaqs_measurement_get(r+8,4),1000)==RemoteImuStream::Accepted);
            exchange(ramAck(out));
        }
    };
    for(unsigned n=0;n<4;++n) {
        RemoteImuBinding b;b.node=n;b.boot=5+n;b.uid=100+n;b.masterBoot=99;b.masterUid=9;
        b.session=1;b.recording=77;b.context=9;b.compactPackets=b.sampleUnits=true;
        assert(streams[n].configure(b,(uint16_t)(2*n+1),(uint16_t)(2*n+2)));
        evidence(n);
        for(unsigned i=0;i<4;++i)
            assert(streams[n].acceptSampleUnit(9,units[n][i].object,units[n][i].body,units[n][i].total,1100+i)==RemoteImuStream::Accepted);
        uint8_t stop[64]={1,0x25,1,0,0,0,56};stop[13]=1;stop[14]=8;
        bodaqs_measurement_put(stop+8,5+n,4);bodaqs_measurement_put(stop+28,59,4);bodaqs_measurement_put(stop+54,0x261,2);
        assert(bodaqs_master_service_receive_can(&master,n,2,0x90+n,stop,64,0,100,30));evidence(n);
    }
    BdqV2StreamDescriptor descriptors[8];
    for(unsigned n=0;n<4;++n) {descriptors[2*n]=streams[n].descriptor(false);descriptors[2*n+1]=streams[n].descriptor(true);}
    const size_t size=BdqV2Catalog::measure("window_four_host",descriptors,8);assert(size);
    std::vector<char> catalog(size+1);size_t length=0;
    assert(BdqV2Catalog::write("window_four_host",descriptors,8,catalog.data(),catalog.size(),length));
    struct Sink: BdqV2ByteSink {
        FILE* file;
        explicit Sink(const char* p):file(std::fopen(p,"wb")){assert(file);}
        ~Sink(){std::fclose(file);}
        bool write(const uint8_t* p,size_t n)override{return std::fwrite(p,1,n,file)==n;}
        bool flush()override{return std::fflush(file)==0;}
    } sink(path);
    uint8_t workspace[4096];BdqV2Writer writer;
    for(const auto& d:descriptors) assert(writer.addStream(d.source));
    const char metadata[]=R"({"format":"bdq.v2","format_name":"BDQLOG v2","recording_id":"window_four_host","device_id":"host","firmware_name":"BODAQS","firmware_version":"host","hardware_version":"host","created_unix_us":0,"timezone":"Australia/Perth","log_format":"bodaqs_multi_stream_binary","native_stream_contract":"bodaqs.native_stream.v1","stream_count":8,"logger_monotonic_clock":{"clock_id":"logger_monotonic","unit":"us","nondecreasing":true}})";
    assert(writer.begin(sink,workspace,sizeof workspace,0,metadata,sizeof metadata-1,catalog.data(),length));
    assert(writer.end("{}",2));assert(!writer.failed());
}
static void samples(unsigned n,unsigned first,unsigned packets=12) {
    for(unsigned i=0;i<packets;++i) {
        uint8_t p[64]={0,0,1,5};bodaqs_measurement_put(p,first+5*i,2);
        for(unsigned j=0;j<5;++j) {p[4+12*j]=uint8_t(0x34+n);p[5+12*j]=0x12;}
        assert(bodaqs_master_service_receive_can(&master,n,1,0x100+n*8,p,64,0,2+i,2));
    }
}
static BodaqsMeasurementSlot ramAck(const BodaqsMeasurementSlot& unit) {
    BodaqsFragmentState state={};uint8_t bytes[216];BodaqsMeasurementSlot ack={};
    assert(bodaqs_fragment_accept(&state,bytes,sizeof bytes,&unit,1,&ack)==1);
    return ack;
}
static void pressureEvidence() {
    reset();samples(0,0);
    auto credits=ready(1);BodaqsMeasurementSlot retained[4];
    for(unsigned i=0;i<4;++i) {retained[i]=exchange(credits);assert(retained[i].kind==2);credits.body[4]|=1u<<(retained[i].object-1);}
    // Samples fill their own backlog. Optional snapshots consume only their
    // allowance; two essential boundaries still reach the independent lane.
    unsigned rejected=0;
    for(unsigned i=0;i<150;++i) {
        uint8_t p[64]={0,0,1,5};bodaqs_measurement_put(p,60+5*i,2);
        rejected+=!bodaqs_master_service_receive_can(&master,0,1,0x100,p,64,0,200+i,2);
    }
    assert(rejected==22);
    uint8_t optional[64]={1,0x23,1,0,0,0,56};
    bodaqs_measurement_put(optional+8,5,4);optional[13]=1;
    for(unsigned i=0;i<20;++i) (void)bodaqs_master_service_receive_can(&master,0,2,0x90,optional,64,0,500+i,2);
    uint8_t boundary[64]={1,0x25,1,0,0,0,56};
    bodaqs_measurement_put(boundary+8,5,4);boundary[13]=1;boundary[14]=2;boundary[54]=0x61;boundary[55]=1;
    assert(bodaqs_master_service_receive_can(&master,0,2,0x90,boundary,64,0,600,2));
    boundary[14]=8;bodaqs_measurement_put(boundary+28,809,4);
    assert(bodaqs_master_service_receive_can(&master,0,2,0x90,boundary,64,0,601,2));
    bool stopped=false;
    for(unsigned i=0;i<20;++i) {
        BodaqsMeasurementSlot poll={};poll.kind=1;poll.context=9;poll.node=0;poll.body[0]=2;
        const auto out=exchange(poll,30);
        if(out.kind==0) break;
        assert(out.kind==3);
        stopped|=out.body[29]==0x25 && out.body[42]==8;
        exchange(ramAck(out),30);
    }
    assert(stopped && !master.loss[0].failed);
    for(const auto& unit:retained) {
        const auto& live=storage.units[0][unit.object-1];
        assert(!memcmp(live.bytes,unit.body,unit.total));
    }
    puts("Full sample backlog sheds optional evidence and retains essential START/STOP independently: PASS");
}
int main(int argc,char** argv) {
    reset();for(unsigned n=0;n<4;++n) samples(n,0);
    auto r=ready();BodaqsMeasurementSlot units[4][4]={};
    // Leave every ACK unsent: four distinct units per source must progress.
    for(unsigned i=0;i<16;++i) {
        auto out=exchange(r);assert(out.kind==2 && out.node<4 && out.object>=1 && out.object<=4);
        assert(!units[out.node][out.object-1].kind);units[out.node][out.object-1]=out;
        r.body[8*out.node+4]|=uint8_t(1u<<(out.object-1));
    }
    assert(exchange(r).kind==0); // all four advertised custody windows full
    if(argc==2) recordFour(argv[1],units);
    const unsigned before=master.objects_acked;
    for(unsigned n=0;n<4;++n) for(unsigned i=0;i<4;++i) {
        const auto& unit=units[n][i];assert(unit.total==212 && unit.body[20]==0x34+n);
        BodaqsFragmentState state={};uint8_t bytes[216];BodaqsMeasurementSlot ack={};
        assert(bodaqs_fragment_accept(&state,bytes,sizeof bytes,&unit,1,&ack)==1);
        auto bad=ack;bad.body[4]^=1;assert(exchange(bad).kind==7);
        assert(exchange(ack).kind==0); // exact RAM retirement, no implied successor credit
        assert(exchange(ack).kind==0); // replay does not free another unit
    }
    assert(master.objects_acked==before+16);
    // Advance the window; replay history cannot retire a reused physical slot.
    samples(0,60,3);auto next=ready(1);bodaqs_measurement_put(next.body,5,4);
    const auto fifth=exchange(next);assert(fifth.kind==2 && fifth.object==5);
    const auto old=ramAck(units[0][0]);exchange(ramAck(fifth));
    assert(exchange(old).kind==7 && master.objects_acked==before+17);
    pressureEvidence();
    reset();samples(0,0);samples(1,0);
    auto repairs=ready(1);
    for(unsigned i=0;i<32;++i) assert(exchange(repairs,30).kind==2);
    exchange(repairs,131); // bounded repair failure, retained for explicit fence
    BodaqsMeasurementSlot poll={};poll.kind=1;poll.context=9;poll.node=0;poll.body[0]=1;
    auto failure=exchange(poll,232);assert(failure.kind==7 && failure.body[1]==14);
    repairs=ready(2);bodaqs_measurement_put(repairs.body,0,4);
    assert(exchange(repairs,233).node==1); // a failed source cannot freeze another
    puts("Four-source immutable windows, explicit zero credits and exact ACK replay: PASS");
}
