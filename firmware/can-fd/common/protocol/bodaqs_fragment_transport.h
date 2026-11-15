#ifndef BODAQS_FRAGMENT_TRANSPORT_H
#define BODAQS_FRAGMENT_TRANSPORT_H
#include "bodaqs_measurement.h"
/* Caller-owned fixed RAM. No allocation, mutable queue identities or ID wrap. */
typedef struct {
    uint64_t context;
    uint32_t object, mask, checksum, accepted;
    uint32_t accepted_object, accepted_checksum;
    uint16_t total, accepted_total;
    uint8_t node, cls, direction, complete;
} BodaqsFragmentState;
static inline uint8_t bodaqs_fragment_kind(uint8_t cls) {
    const uint8_t kinds[6]={0,2,3,4,12,13};
    return cls<6?kinds[cls]:0;
}
static inline uint8_t bodaqs_fragment_class(uint8_t kind) {
    switch(kind) { case 2:return 1; case 3:return 2; case 4:return 3; case 12:return 4; case 13:return 5; default:return 0; }
}
static inline uint32_t bodaqs_fragment_checksum(const BodaqsFragmentState *s,const uint8_t *data) {
    uint8_t prefix[20]={0}; uint32_t c=0xffffffffU; unsigned i;
    bodaqs_measurement_put(prefix,s->context,8); bodaqs_measurement_put(prefix+8,s->object,4);
    prefix[12]=s->node; prefix[13]=s->cls; prefix[14]=s->direction;
    bodaqs_measurement_put(prefix+16,s->total,2);
#if BODAQS_MASTER_BLOCK_CRC
    /* Same canonical concatenation, without choosing prefix/data per byte. */
    (void)i;
    c=bodaqs_measurement_crc_update(c,prefix,sizeof prefix);
    c=bodaqs_measurement_crc_update(c,data,s->total-4U);
#else
    for(i=0;i<(unsigned)(20+s->total-4);++i) {
        c=bodaqs_measurement_crc_step(c,i<20?prefix[i]:data[i-20]);
    }
#endif
    return ~c;
}
static inline bool bodaqs_fragment_seal(BodaqsFragmentState *s,uint8_t *data,size_t capacity,
    uint64_t context,uint32_t object,uint8_t node,uint8_t cls,uint8_t direction,uint16_t length) {
    if(!s || !data || !context || !object || !bodaqs_fragment_kind(cls) || direction>1 ||
       (node>3 && !(node==255 && cls==5)) || length>1020 || length+4U>capacity) return false;
    memset(s,0,sizeof(*s)); s->context=context; s->object=object; s->node=node;
    s->cls=cls; s->direction=direction; s->total=length+4; s->complete=1;
    s->checksum=bodaqs_fragment_checksum(s,data);
    bodaqs_measurement_put(data+length,s->checksum,4); return true;
}
static inline bool bodaqs_fragment_emit(const BodaqsFragmentState *s,const uint8_t *data,
    uint8_t index,BodaqsMeasurementSlot *slot) {
    unsigned offset=(unsigned)index*BODAQS_MEASUREMENT_BODY_BYTES, count;
    if(!s->complete || offset>=s->total) return false;
    count=s->total-offset; if(count>BODAQS_MEASUREMENT_BODY_BYTES) count=BODAQS_MEASUREMENT_BODY_BYTES;
    /* Initialize metadata, padding and unused body bytes; the complete valid
     * payload is overwritten once below. Include proof fields after body. */
    const size_t prefix=offsetof(BodaqsMeasurementSlot,body);
    memset(slot,0,prefix);
    memset((uint8_t *)slot+prefix+count,0,sizeof(*slot)-prefix-count);
    slot->kind=bodaqs_fragment_kind(s->cls);
    slot->context=s->context; slot->object=s->object; slot->node=s->node; slot->index=index; slot->total=s->total;
    memcpy(slot->body,data+offset,count); return true;
}
static inline void bodaqs_fragment_ack(const BodaqsFragmentState *s,uint8_t disposition,BodaqsMeasurementSlot *ack) {
    memset(ack,0,sizeof(*ack)); ack->kind=5; ack->context=s->context; ack->object=s->object;
    ack->node=s->node; ack->total=s->total; ack->body[0]=s->cls; ack->body[1]=disposition;
    bodaqs_measurement_put(ack->body+4,s->checksum,4);
}
static inline bool bodaqs_fragment_ack_matches(const BodaqsFragmentState *s,const BodaqsMeasurementSlot *a) {
    return s->complete && a->kind==5 && a->context==s->context && a->object==s->object &&
        a->node==s->node && a->total==s->total && !a->index && a->body[0]==s->cls &&
        (a->body[1]==1 || a->body[1]==2) && bodaqs_measurement_zero(a->body+2,2) &&
        bodaqs_measurement_get(a->body+4,4)==s->checksum && bodaqs_measurement_zero(a->body+8,BODAQS_MEASUREMENT_BODY_BYTES-8);
}
/* 0 incomplete, 1 new validated RAM object, 2 cached duplicate; negative ERROR reason.
 * Complete RAM remains pinned until caller has admitted it downstream. */
static inline int bodaqs_fragment_accept(BodaqsFragmentState *s,uint8_t *data,size_t capacity,
    const BodaqsMeasurementSlot *a,uint8_t direction,BodaqsMeasurementSlot *ack) {
    uint8_t cls=bodaqs_fragment_class(a->kind); unsigned offset=(unsigned)a->index*BODAQS_MEASUREMENT_BODY_BYTES,count;
    uint32_t bit, all;
    if(!cls || !a->object || !a->context || direction>1 ||
       (a->node>3 && !(a->node==255 && cls==5))) return -13;
    if(a->total<4 || a->total>1024 || a->total>capacity || offset>=a->total ||
       ((cls==3 || cls==4) && a->total!=68) ||
       ((cls==1 && BODAQS_MEASUREMENT_VERSION>=3)?
           (a->index || a->total<84 || a->total>BODAQS_SAMPLE_UNIT_MAX || (a->total-20)%64):
           ((cls==1 || cls==2) && (a->total<96 || (a->total-20)%76))) ||
       (cls==5 && (a->total<28 || (a->total-12)%16))) return -2;
    count=a->total-offset; if(count>BODAQS_MEASUREMENT_BODY_BYTES) count=BODAQS_MEASUREMENT_BODY_BYTES;
    if(!bodaqs_measurement_zero(a->body+count,BODAQS_MEASUREMENT_BODY_BYTES-count)) return -2;
    if(s->object && (s->context!=a->context || s->node!=a->node || s->cls!=cls || s->direction!=direction)) return -4;
    if(s->object && a->object!=s->object && a->object==s->accepted_object) {
        BodaqsFragmentState cached=*s;
        if(a->total!=s->accepted_total) return -5;
        if(offset<=a->total-4U && offset+count==a->total &&
           bodaqs_measurement_get(a->body+count-4,4)!=s->accepted_checksum) return -5;
        cached.object=s->accepted_object;cached.total=s->accepted_total;cached.checksum=s->accepted_checksum;
        bodaqs_fragment_ack(&cached,2,ack);return 2;
    }
    if(s->object && a->object<s->object) return -6;
    if(s->object && a->object!=s->object && !s->complete) return -8;
    if(a->object!=s->object) {
        uint32_t accepted=s->accepted, object=s->accepted_object, checksum=s->accepted_checksum;
        uint16_t total=s->accepted_total;
        memset(s,0,sizeof(*s)); s->accepted=accepted;
        s->accepted_object=object;s->accepted_checksum=checksum;s->accepted_total=total;
        s->context=a->context; s->object=a->object; s->node=a->node;
        s->cls=cls; s->direction=direction; s->total=a->total;
    }
    if(a->total!=s->total) return -5;
    bit=1UL<<a->index;
    if((s->mask&bit) && memcmp(data+offset,a->body,count)) return -5;
    if(s->complete) { bodaqs_fragment_ack(s,2,ack); return 2; }
    memcpy(data+offset,a->body,count); s->mask|=bit;
    all=(1UL<<((s->total+BODAQS_MEASUREMENT_BODY_BYTES-1)/BODAQS_MEASUREMENT_BODY_BYTES))-1;
    if(s->mask!=all) return 0;
    s->checksum=(uint32_t)bodaqs_measurement_get(data+s->total-4,4);
    if(s->checksum!=bodaqs_fragment_checksum(s,data)) { s->mask=0; return -3; }
    if(cls==1 && BODAQS_MEASUREMENT_VERSION>=3) {
        unsigned records=(s->total-20)/64;
        if(bodaqs_measurement_get(data,2)!=2 || data[2]!=1 || data[3]!=s->node ||
           !bodaqs_measurement_get(data+4,4) || bodaqs_measurement_get(data+12,2)!=records ||
           !bodaqs_measurement_zero(data+14,2)) {s->mask=0;return -13;}
        for(unsigned i=0;i<records;++i) {
            const uint8_t *packet=data+16+64*i;unsigned count=packet[3]&7;
            if(!count || count>5 || (packet[3]&128) ||
               !bodaqs_measurement_zero(packet+4+12*count,60-12*count)) {s->mask=0;return -13;}
        }
    } else if(cls==1 || cls==2) {
        unsigned i,records=(s->total-20)/76;
        if(bodaqs_measurement_get(data,2)!=1 || data[2]!=cls || data[3]!=s->node ||
           !bodaqs_measurement_get(data+4,4) || bodaqs_measurement_get(data+12,2)!=records ||
           !bodaqs_measurement_zero(data+14,2)) {s->mask=0;return -13;}
        for(i=0;i<records;++i) {
            const uint8_t *record=data+16+i*76;
            uint16_t id=(uint16_t)bodaqs_measurement_get(record,2);
            if(record[2]>64 || !bodaqs_measurement_zero(record+12+record[2],64-record[2]) ||
               (cls==1?id!=0x100U+s->node*8U:(id!=0x060U+s->node && id!=0x090U+s->node))) {
                s->mask=0;return -13;
            }
        }
    }
    if(cls==5) {
        unsigned i,count=(s->total-12)/16;
        if(bodaqs_measurement_get(data,2)!=1 || data[2]!=1 ||
           bodaqs_measurement_get(data+4,2)!=count || !bodaqs_measurement_zero(data+6,2)) {
            s->mask=0;return -13;
        }
        for(i=0;i<count;++i) if(data[8+i*16]!=1 || data[9+i*16]) {s->mask=0;return -13;}
    }
    s->complete=1; ++s->accepted;
    s->accepted_object=s->object;s->accepted_checksum=s->checksum;s->accepted_total=s->total;
    bodaqs_fragment_ack(s,1,ack); return 1;
}
#endif
