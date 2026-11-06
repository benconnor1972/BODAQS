#include "bodaqs_spi_probe.h"
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
#include <string.h>
static void put32(uint8_t *p,uint32_t x) {
    for(unsigned i=0;i<4;++i) p[i]=(uint8_t)(x>>(8*i));
}
static uint32_t get32(const uint8_t *p) {
    return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);
}
uint16_t bodaqs_spi_probe_frame_bytes(uint8_t p) {
    return (p&0xe0U) || (p&3U)==3U ? 0 : (uint16_t)(64U<<(p&3U));
}
uint8_t bodaqs_spi_probe_node_count(uint8_t p) {return (uint8_t)(((p>>3)&3U)+1U);}
uint8_t bodaqs_spi_probe_profile(uint16_t bytes,uint32_t hz,uint8_t nodes) {
    if((bytes!=64 && bytes!=128 && bytes!=256) || (hz!=8000000 && hz!=16000000) || !nodes || nodes>4) return 255;
    return (uint8_t)((bytes==64?0:bytes==128?1:2)|(hz==16000000?4:0)|((nodes-1)<<3));
}
uint8_t bodaqs_spi_probe_fragment_count(uint8_t p) {
    uint16_t bytes=bodaqs_spi_probe_frame_bytes(p);
    return bytes?(uint8_t)((1008U+bytes-25U)/(bytes-24U)):0;
}
#ifndef BODAQS_SPI_PROBE_CRC_TABLE
#define BODAQS_SPI_PROBE_CRC_TABLE 0
#endif
#if BODAQS_SPI_PROBE_CRC_TABLE != 0 && BODAQS_SPI_PROBE_CRC_TABLE != 1
#error "BODAQS_SPI_PROBE_CRC_TABLE must be0 or1"
#endif
#if BODAQS_SPI_PROBE_CRC_TABLE
#include "bodaqs_measurement.h"
#endif
/* Main-owned engine context is explicit; public stateless codec calls have no
 * timing side effects. Nested totals overlap and must not be added together. */
typedef struct {uint32_t tick,epoch;} ComponentStart;
static ComponentStart component_start(BodaqsSpiProbeEngine *e) {
    ComponentStart s={0,0};
    if(e && e->component_clock)s.tick=e->component_clock(e->component_clock_arg,&s.epoch);
    return s;
}
static void component_end(BodaqsSpiProbeEngine *e,unsigned index,ComponentStart start) {
    if(!e || !e->component_clock)return;
    uint32_t epoch=0,now=e->component_clock(e->component_clock_arg,&epoch);
    ++e->component_stats[index];
    if(!start.epoch || epoch!=start.epoch || (e->component_epoch && e->component_epoch!=epoch))e->component_invalid=1;
    else e->component_stats[index+1]+=now-start.tick;
    e->component_epoch=epoch;
}
static uint32_t crc_step(uint32_t crc,uint8_t byte) {
    #if BODAQS_SPI_PROBE_CRC_TABLE
    return bodaqs_measurement_crc_step(crc,byte);
    #else
    crc^=byte;
    for(unsigned bit=0;bit<8;++bit) crc=(crc>>1)^(0xedb88320U & (0U-(crc&1U)));
    return crc;
    #endif
}
uint32_t bodaqs_spi_probe_crc(const uint8_t *bytes,size_t length) {
    uint32_t crc=0xffffffffU;
    for(size_t i=0;i<length;++i) crc=crc_step(crc,bytes[i]);
    return crc^0xffffffffU;
}
uint8_t bodaqs_spi_probe_known_byte(uint32_t c,uint8_t n,uint32_t o,uint16_t i) {
    return (uint8_t)(c*17U+n*29U+o*37U+i*13U+(i>>8)*7U);
}
uint32_t bodaqs_spi_probe_known_crc(uint32_t c,uint8_t n,uint32_t o) {
    uint32_t crc=0xffffffffU;
    for(uint16_t i=0;i<1008;++i) crc=crc_step(crc,bodaqs_spi_probe_known_byte(c,n,o,i));
    return crc^0xffffffffU;
}
static bool encode(const BodaqsSpiProbeFrame *f,uint8_t *w,size_t length,BodaqsSpiProbeEngine *e) {
    if(!f || !w || (length!=64 && length!=128 && length!=256) ||
        length!=bodaqs_spi_probe_frame_bytes(f->profile) || f->payload_length>length-24U) return false;
    memset(w,0,length); w[0]=0x53;w[1]=0x50;w[2]=1;w[3]=f->opcode;
    put32(w+4,f->case_id);put32(w+8,f->object_id);
    w[12]=f->node;w[13]=f->fragment;w[14]=f->payload_length;w[15]=f->profile;
    put32(w+16,f->logical_crc);memcpy(w+20,f->payload,f->payload_length);
    ComponentStart began=component_start(e);
    put32(w+length-4,bodaqs_spi_probe_crc(w,length-4));component_end(e,6,began);return true;
}
static BodaqsSpiProbeDecodeResult decode(const uint8_t *w,size_t length,BodaqsSpiProbeFrame *f,BodaqsSpiProbeEngine *e) {
    if(!w || !f) return BODAQS_SPI_PROBE_DECODE_ARGUMENT;
    if(length!=64 && length!=128 && length!=256) return BODAQS_SPI_PROBE_DECODE_FRAME_SIZE;
    if(w[0]!=0x53 || w[1]!=0x50) return BODAQS_SPI_PROBE_DECODE_MAGIC;
    if(w[2]!=1) return BODAQS_SPI_PROBE_DECODE_VERSION;
    if(length!=bodaqs_spi_probe_frame_bytes(w[15])) return BODAQS_SPI_PROBE_DECODE_PROFILE;
    if(w[14]>length-24) return BODAQS_SPI_PROBE_DECODE_PAYLOAD_LENGTH;
    ComponentStart began=component_start(e);
    const uint32_t crc=bodaqs_spi_probe_crc(w,length-4);component_end(e,6,began);
    if(get32(w+length-4)!=crc) return BODAQS_SPI_PROBE_DECODE_CRC;
    for(size_t i=20U+w[14];i<length-4;++i) if(w[i]) return BODAQS_SPI_PROBE_DECODE_PADDING;
    memset(f,0,sizeof *f);f->opcode=w[3];f->case_id=get32(w+4);f->object_id=get32(w+8);
    f->node=w[12];f->fragment=w[13];f->payload_length=w[14];f->profile=w[15];f->logical_crc=get32(w+16);
    memcpy(f->payload,w+20,f->payload_length);return BODAQS_SPI_PROBE_DECODE_OK;
}
bool bodaqs_spi_probe_encode(const BodaqsSpiProbeFrame *f,uint8_t *w,size_t length) {return encode(f,w,length,NULL);}
BodaqsSpiProbeDecodeResult bodaqs_spi_probe_decode_result(const uint8_t *w,size_t length,BodaqsSpiProbeFrame *f) {return decode(w,length,f,NULL);}
bool bodaqs_spi_probe_decode(const uint8_t *w,size_t length,BodaqsSpiProbeFrame *f) {
    return bodaqs_spi_probe_decode_result(w,length,f)==BODAQS_SPI_PROBE_DECODE_OK;
}
void bodaqs_spi_probe_init(BodaqsSpiProbeEngine *e) {memset(e,0,sizeof *e);}
void bodaqs_spi_probe_set_clock(BodaqsSpiProbeEngine *e,uint32_t (*clock)(void *,uint32_t *),void *arg) {
    e->component_clock=clock;e->component_clock_arg=arg;
}
static uint8_t fragment(BodaqsSpiProbeEngine *e,const BodaqsSpiProbeFrame *q,BodaqsSpiProbeFrame *r) {
    BodaqsSpiProbeNode *n=&e->nodes[q->node];
    unsigned capacity=bodaqs_spi_probe_frame_bytes(e->profile)-24U;
    unsigned offset=q->fragment*capacity;
    if(offset>=1008) return BODAQS_PROBE_ARGUMENT;
    if(!n->selected) {
        if(n->object_id==UINT32_MAX) return BODAQS_PROBE_EXHAUSTED;
        if(q->object_id && q->object_id!=n->object_id+1U) return BODAQS_PROBE_CONTEXT;
        ++n->object_id;ComponentStart began=component_start(e);
        n->logical_crc=bodaqs_spi_probe_known_crc(e->case_id,q->node,n->object_id);component_end(e,8,began);
        n->selected=true;n->prepared_mask=0;++e->stats.selected_objects;
    }
    if(q->object_id && q->object_id!=n->object_id) return BODAQS_PROBE_CONTEXT;
    r->object_id=n->object_id;r->logical_crc=n->logical_crc;
    r->payload_length=(uint8_t)(1008U-offset<capacity?1008U-offset:capacity);
    for(unsigned i=0;i<r->payload_length;++i)
        r->payload[i]=bodaqs_spi_probe_known_byte(e->case_id,q->node,n->object_id,(uint16_t)(offset+i));
    if(n->prepared_mask&(1U<<q->fragment)) ++e->stats.repeat_fragments;
    n->prepared_mask|=1U<<q->fragment;++e->stats.prepared_fragments;
    return BODAQS_PROBE_OK;
}
static uint8_t command(BodaqsSpiProbeEngine *e,BodaqsSpiProbeFrame *q,BodaqsSpiProbeFrame *r) {
    if(!q->case_id || q->payload_length) return BODAQS_PROBE_ARGUMENT;
    if(q->opcode==BODAQS_PROBE_BEGIN) {
        if(q->object_id || q->logical_crc || q->node || q->fragment) return BODAQS_PROBE_ARGUMENT;
        if(e->active) return e->case_id==q->case_id && e->profile==q->profile?BODAQS_PROBE_OK:BODAQS_PROBE_BUSY;
        /* Monotonic IDs prevent reuse of earlier case/object acknowledgement. */
        if(q->case_id<=e->case_id) return BODAQS_PROBE_CONTEXT;
        e->case_id=q->case_id;e->profile=q->profile;e->active=true;
        memset(e->nodes,0,sizeof e->nodes);++e->stats.cases;return BODAQS_PROBE_OK;
    }
    if(q->case_id!=e->case_id || q->profile!=e->profile) return BODAQS_PROBE_CONTEXT;
    if(q->opcode==BODAQS_PROBE_STATS || q->opcode==BODAQS_PROBE_STOP) {
        if(q->object_id || q->logical_crc || q->node) return BODAQS_PROBE_ARGUMENT;
        if(q->opcode==BODAQS_PROBE_STOP) {
            if(q->fragment) return BODAQS_PROBE_ARGUMENT;
            e->active=false;return BODAQS_PROBE_OK;
        }
        if(q->fragment>4) return BODAQS_PROBE_ARGUMENT;
        const uint32_t counters[]={e->stats.requests,e->stats.malformed,e->stats.rejected,
            e->stats.prepared_fragments,e->stats.repeat_fragments,e->stats.selected_objects,
            e->stats.retired_objects,e->stats.duplicate_acks,e->stats.bad_acks,e->stats.cases};
        r->payload_length=40;
        const uint32_t metadata[]={1,BODAQS_SPI_PROBE_CRC_TABLE,e->component_epoch,e->component_invalid,e->component_clock!=NULL,0,0,0,0,0};
        const uint32_t *page=q->fragment==4?metadata:q->fragment==3?e->component_stats:
            q->fragment==2?e->diagnostic_stats:q->fragment?e->adapter_stats:counters;
        for(unsigned i=0;i<10;++i) put32(r->payload+4*i,page[i]);
        return BODAQS_PROBE_OK;
    }
    if(!e->active) return BODAQS_PROBE_CONTEXT;
    if(q->node>=bodaqs_spi_probe_node_count(e->profile)) return BODAQS_PROBE_ARGUMENT;
    if(q->opcode==BODAQS_PROBE_POLL) {
        if(q->logical_crc) return BODAQS_PROBE_ARGUMENT;
        return fragment(e,q,r);
    }
    if(q->opcode==BODAQS_PROBE_ACK || q->opcode==BODAQS_PROBE_ACK_FETCH) {
        BodaqsSpiProbeNode *n=&e->nodes[q->node];
        if(q->fragment || !q->object_id) return BODAQS_PROBE_ARGUMENT;
        if(n->last_acked==q->object_id && n->last_acked_crc==q->logical_crc) ++e->stats.duplicate_acks;
        else {
            if(!n->selected || n->object_id!=q->object_id) {++e->stats.bad_acks;return BODAQS_PROBE_CONTEXT;}
            if(n->logical_crc!=q->logical_crc) {++e->stats.bad_acks;return BODAQS_PROBE_CHECKSUM;}
            n->last_acked=q->object_id;n->last_acked_crc=q->logical_crc;
            n->selected=false;++e->stats.retired_objects;
        }
        if(q->opcode==BODAQS_PROBE_ACK_FETCH) {q->object_id=0;q->logical_crc=0;return fragment(e,q,r);}
        return BODAQS_PROBE_OK;
    }
    return BODAQS_PROBE_ARGUMENT;
}
bool bodaqs_spi_probe_process(BodaqsSpiProbeEngine *e,const uint8_t *request,size_t length,uint8_t *reply,size_t capacity) {
    BodaqsSpiProbeFrame q,r;uint8_t status;
    if(!e || !reply) return false;
    ++e->stats.requests;
    if(capacity<length) {++e->stats.malformed;return false;}
    ComponentStart began=component_start(e);
    BodaqsSpiProbeDecodeResult decoded=decode(request,length,&q,e);component_end(e,0,began);
    if(decoded!=BODAQS_SPI_PROBE_DECODE_OK) {++e->stats.malformed;return false;}
    r=q;r.opcode|=BODAQS_PROBE_RESPONSE;r.payload_length=0;
    began=component_start(e);status=command(e,&q,&r);component_end(e,2,began);
    if(status) {++e->stats.rejected;r.opcode=255;r.payload_length=1;r.payload[0]=status;}
    else if(!r.payload_length) {r.payload_length=1;r.payload[0]=0;}
    began=component_start(e);memset(reply,0,capacity);
    bool prepared=encode(&r,reply,length,e);component_end(e,4,began);return prepared;
}
#endif
