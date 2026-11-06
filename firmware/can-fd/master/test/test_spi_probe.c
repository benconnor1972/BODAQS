#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "bodaqs_spi_probe.h"
static BodaqsSpiProbeFrame exchange(BodaqsSpiProbeEngine *e,BodaqsSpiProbeFrame *q) {
    uint8_t tx[256],rx[256];BodaqsSpiProbeFrame r;
    size_t size=bodaqs_spi_probe_frame_bytes(q->profile);
    assert(bodaqs_spi_probe_encode(q,tx,size));
    assert(bodaqs_spi_probe_process(e,tx,size,rx,sizeof rx));
    assert(bodaqs_spi_probe_decode(rx,size,&r));
    for(size_t i=size;i<sizeof rx;++i) assert(rx[i]==0);
    return r;
}
int main(void) {
    uint8_t wire[256]; BodaqsSpiProbeFrame f={0}, decoded;
    f.profile=255;assert(!bodaqs_spi_probe_encode(&f,wire,0));
    assert(bodaqs_spi_probe_crc((const uint8_t *)"123456789",9)==0xcbf43926U);
    for(unsigned size=64;size<=256;size*=2) {
        f.profile=bodaqs_spi_probe_profile((uint16_t)size,16000000,4);
        f.opcode=BODAQS_PROBE_BEGIN; f.case_id=1;
        assert(bodaqs_spi_probe_encode(&f,wire,size));
        assert(wire[0]==0x53 && wire[1]==0x50 && wire[4]==1);
        assert(bodaqs_spi_probe_decode(wire,size,&decoded));
        assert(decoded.case_id==1 && decoded.profile==f.profile);
        wire[size-1]^=1;
        assert(!bodaqs_spi_probe_decode(wire,size,&decoded));
        assert(!bodaqs_spi_probe_decode(wire,size-1,&decoded));
    }
    puts("probe codec geometry and independent CRC vector: PASS");
    for(unsigned size=64;size<=256;size*=2) {
        BodaqsSpiProbeEngine e; bodaqs_spi_probe_init(&e);
        BodaqsSpiProbeFrame q={0},r;
        q.profile=bodaqs_spi_probe_profile((uint16_t)size,8000000,4);
        q.case_id=1;q.opcode=BODAQS_PROBE_BEGIN;
        r=exchange(&e,&q);assert(r.opcode==129 && r.payload[0]==0);
        r=exchange(&e,&q);assert(r.opcode==129 && e.stats.cases==1);
        q.opcode=BODAQS_PROBE_STATS;q.fragment=1;
        e.adapter_stats[1]=19;r=exchange(&e,&q);
        assert(r.opcode==133 && r.fragment==1 && r.payload_length==40 && r.payload[4]==19);
        q.opcode=BODAQS_PROBE_BEGIN;q.fragment=0;
        q.case_id=2;r=exchange(&e,&q);assert(r.opcode==255 && r.payload[0]==BODAQS_PROBE_BUSY);q.case_id=1;
        for(uint8_t n=0;n<4;++n) {
            uint8_t accepted[1008];q.opcode=BODAQS_PROBE_POLL;q.node=n;
            unsigned used=0;
            for(unsigned i=0;i<bodaqs_spi_probe_fragment_count(q.profile);++i) {
                q.fragment=(uint8_t)i;r=exchange(&e,&q);
                assert(r.opcode==130 && r.object_id==1 && r.fragment==i);
                memcpy(accepted+used,r.payload,r.payload_length);used+=r.payload_length;
                BodaqsSpiProbeFrame replay=exchange(&e,&q);
                assert(memcmp(&r,&replay,sizeof r)==0);
            }
            assert(used==1008);
            /* Independently generated fixture prefix and zlib CRC at case1/node0/object1. */
            if(n==0) {
                static const uint8_t prefix[]={0x36,0x43,0x50,0x5d,0x6a,0x77,0x84,0x91,0x9e,0xab,0xb8,0xc5,0xd2,0xdf,0xec,0xf9};
                assert(!memcmp(accepted,prefix,sizeof prefix));
                assert(bodaqs_spi_probe_crc(accepted,1008)==0x2c64f296U && r.logical_crc==0x2c64f296U);
            }
            q.opcode=BODAQS_PROBE_ACK;q.fragment=0;q.object_id=1;q.logical_crc=r.logical_crc^1;
            r=exchange(&e,&q);assert(r.opcode==255 && r.payload[0]==BODAQS_PROBE_CHECKSUM);
            q.logical_crc^=1;q.opcode=BODAQS_PROBE_ACK_FETCH;
            r=exchange(&e,&q);assert(r.opcode==132 && r.object_id==2);
            r=exchange(&e,&q);assert(r.opcode==132 && r.object_id==2);
            assert(e.stats.retired_objects==n+1U);
            q.object_id=0;q.logical_crc=0;
        }
        q=(BodaqsSpiProbeFrame){.profile=q.profile,.case_id=1,.opcode=BODAQS_PROBE_STOP};
        r=exchange(&e,&q);assert(r.opcode==134 && !e.active);
        r=exchange(&e,&q);assert(r.opcode==134);
        q.opcode=BODAQS_PROBE_BEGIN;r=exchange(&e,&q);assert(r.opcode==255);
        q.case_id=2;r=exchange(&e,&q);assert(r.opcode==129);
        q.case_id=1;q.opcode=BODAQS_PROBE_ACK;r=exchange(&e,&q);assert(r.opcode==255);
        q.case_id=2;q.opcode=BODAQS_PROBE_POLL;q.object_id=99;
        r=exchange(&e,&q);assert(r.opcode==255 && e.stats.selected_objects==8);
        assert(!e.nodes[0].selected); /* Rejected identity cannot select/replace. */
    }
    puts("immutable objects, RAM ACK, replay, clean case entry/exit all geometries: PASS");
    return 0;
}
