#include "packed_reply.h"
#include "bodaqs_measurement.h"
static bool item_valid(const BpItem *i) {
    if(!i->body || !i->object || i->length>468) return false;
    switch(i->kind) {
    case 2:return i->node<4 && i->length>=84 && (i->length-20)%64==0;
    case 3:return i->node<4 && i->length>=96 && (i->length-20)%76==0;
    case 4:case 12:return i->node<4 && i->length==68;
    case 13:return i->node==255 && i->length>=28 && (i->length-12)%16==0;
    default:return false;
    }
}
static bool duplicate(const BpReply *r,unsigned n) {
    for(unsigned j=0;j<n;++j) if(r->items[j].kind==r->items[n].kind &&
        r->items[j].node==r->items[n].node && r->items[j].object==r->items[n].object) return true;
    return false;
}
bool bp_encode(const BpReply *r,uint8_t wire[BP_BYTES]) {
    if(!r || !wire || !r->context || !r->sequence || r->count>BP_MAX_ITEMS) return false;
    unsigned used=0;
    for(unsigned n=0;n<r->count;++n) {
        if(!item_valid(&r->items[n]) || duplicate(r,n)) return false;
        used+=8+r->items[n].length;
    }
    if(used>BP_BODY) return false;
    memset(wire,0,BP_BYTES);memcpy(wire,"B51P",4);wire[4]=BP_WIRE_VERSION;wire[5]=r->count;
    bodaqs_measurement_put(wire+8,r->context,8);bodaqs_measurement_put(wire+16,r->sequence,4);
    bodaqs_measurement_put(wire+20,used,2);bodaqs_measurement_put(wire+24,r->confirmed_command,4);
#if BODAQS_PACKED_PROGRESS
    bodaqs_measurement_put(wire+28,r->confirmed_metadata,4);
#endif
    unsigned offset=32;
    for(unsigned n=0;n<r->count;++n) {
        const BpItem *i=&r->items[n];wire[offset]=i->kind;wire[offset+1]=i->node;
        bodaqs_measurement_put(wire+offset+2,i->length,2);bodaqs_measurement_put(wire+offset+4,i->object,4);
        memcpy(wire+offset+8,i->body,i->length);offset+=8+i->length;
    }
    bodaqs_measurement_put(wire+508,bodaqs_measurement_crc(wire,508),4);return true;
}
bool bp_decode(const uint8_t *wire,size_t bytes,uint64_t context,BpReply *out) {
    if(!wire || !out || bytes!=BP_BYTES || !context || memcmp(wire,"B51P",4) || wire[4]!=BP_WIRE_VERSION ||
       wire[5]>BP_MAX_ITEMS || !bodaqs_measurement_zero(wire+6,2) ||
       (!bodaqs_measurement_zero(wire+22,2) || (BODAQS_PACKED_PROGRESS ? false : !bodaqs_measurement_zero(wire+28,4))) || bodaqs_measurement_get(wire+8,8)!=context ||
       !bodaqs_measurement_get(wire+16,4) ||
       bodaqs_measurement_get(wire+508,4)!=bodaqs_measurement_crc(wire,508)) return false;
    unsigned used=(unsigned)bodaqs_measurement_get(wire+20,2),offset=32;
    if(used>BP_BODY || !bodaqs_measurement_zero(wire+32+used,BP_BODY-used)) return false;
    BpReply r={0};r.context=context;r.sequence=(uint32_t)bodaqs_measurement_get(wire+16,4);r.count=wire[5];r.confirmed_command=(uint32_t)bodaqs_measurement_get(wire+24,4);
#if BODAQS_PACKED_PROGRESS
    r.confirmed_metadata=(uint32_t)bodaqs_measurement_get(wire+28,4);
#endif
    for(unsigned n=0;n<r.count;++n) {
        if(offset+8>32+used) return false;
        BpItem *i=&r.items[n];i->kind=wire[offset];i->node=wire[offset+1];
        i->length=(uint16_t)bodaqs_measurement_get(wire+offset+2,2);i->object=(uint32_t)bodaqs_measurement_get(wire+offset+4,4);
        if(offset+8+i->length>32+used) return false;
        i->body=wire+offset+8;
        if(!item_valid(i) || duplicate(&r,n)) return false;
        offset+=8+i->length;
    }
    if(offset!=32+used) return false;
    *out=r;return true;
}
static bool ack_valid(const BpAck *a) {
    static const uint8_t kinds[6]={0,2,3,4,12,13};
    const uint8_t dummy=0;
    if(a->cls<(BODAQS_PACKED_PROGRESS?2:1) || a->cls>5 || (a->disposition!=1 && a->disposition!=2)) return false;
    BpItem item={&dummy,a->object,a->total,kinds[a->cls],a->node};
    return item_valid(&item);
}
static bool ack_duplicate(const BpCommand *c,unsigned n) {
    for(unsigned j=0;j<n;++j) if(c->acks[j].cls==c->acks[n].cls &&
       c->acks[j].node==c->acks[n].node && c->acks[j].object==c->acks[n].object) return true;
    return false;
}
bool bp_command_encode(const BpCommand *c,uint8_t wire[BP_COMMAND_BYTES]) {
    if(!c || !wire || !c->context || !c->sequence || c->count>BP_MAX_ACKS) return false;
    for(unsigned n=0;n<c->count;++n) if(!ack_valid(&c->acks[n]) || ack_duplicate(c,n)) return false;
    memset(wire,0,BP_COMMAND_BYTES);memcpy(wire,"B51C",4);wire[4]=BP_WIRE_VERSION;wire[5]=c->count;
    bodaqs_measurement_put(wire+8,c->context,8);bodaqs_measurement_put(wire+16,c->sequence,4);
#if BODAQS_PACKED_PROGRESS
    if((c->count!=0)!=(c->metadata_sequence!=0))return false;
    bodaqs_measurement_put(wire+20,c->metadata_sequence,4);
#endif
    memcpy(wire+24,c->sample_words,32);
    for(unsigned n=0;n<c->count;++n) {
        unsigned off=56+16*n;const BpAck *a=&c->acks[n];
        bodaqs_measurement_put(wire+off,a->object,4);bodaqs_measurement_put(wire+off+4,a->checksum,4);
        bodaqs_measurement_put(wire+off+8,a->total,2);wire[off+10]=a->node;
        wire[off+11]=a->cls;wire[off+12]=a->disposition;
    }
    bodaqs_measurement_put(wire+252,bodaqs_measurement_crc(wire,252),4);return true;
}
bool bp_command_decode(const uint8_t *wire,size_t bytes,uint64_t context,BpCommand *out) {
    if(!wire || !out || bytes!=BP_COMMAND_BYTES || !context || memcmp(wire,"B51C",4) || wire[4]!=BP_WIRE_VERSION ||
       wire[5]>BP_MAX_ACKS || !bodaqs_measurement_zero(wire+6,2) ||
       (BODAQS_PACKED_PROGRESS ? false : !bodaqs_measurement_zero(wire+20,4)) || bodaqs_measurement_get(wire+8,8)!=context ||
       !bodaqs_measurement_get(wire+16,4) ||
       !bodaqs_measurement_zero(wire+56+16*wire[5],196-16*wire[5]) ||
       bodaqs_measurement_get(wire+252,4)!=bodaqs_measurement_crc(wire,252)) return false;
    BpCommand c={0};c.context=context;c.sequence=(uint32_t)bodaqs_measurement_get(wire+16,4);
    c.count=wire[5];memcpy(c.sample_words,wire+24,32);
#if BODAQS_PACKED_PROGRESS
    c.metadata_sequence=(uint32_t)bodaqs_measurement_get(wire+20,4);
    if((c.count!=0)!=(c.metadata_sequence!=0))return false;
#endif
    for(unsigned n=0;n<c.count;++n) {
        unsigned off=56+16*n;BpAck *a=&c.acks[n];
        a->object=(uint32_t)bodaqs_measurement_get(wire+off,4);a->checksum=(uint32_t)bodaqs_measurement_get(wire+off+4,4);
        a->total=(uint16_t)bodaqs_measurement_get(wire+off+8,2);a->node=wire[off+10];
        a->cls=wire[off+11];a->disposition=wire[off+12];
        if(!bodaqs_measurement_zero(wire+off+13,3) || !ack_valid(a) || ack_duplicate(&c,n)) return false;
    }
    *out=c;return true;
}
