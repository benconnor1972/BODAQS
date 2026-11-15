#ifndef BODAQS_MEASUREMENT_H
#define BODAQS_MEASUREMENT_H
/* Canonical wire codec shared by the logger and master. No wire structs. */
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#ifndef BODAQS_MASTER_CRC_RAM
#define BODAQS_MASTER_CRC_RAM 0
#endif
#if BODAQS_MASTER_CRC_RAM != 0 && BODAQS_MASTER_CRC_RAM != 1
#error "BODAQS_MASTER_CRC_RAM must be 0 or 1"
#endif
#define BODAQS_MEASUREMENT_CAPABILITY (1UL << 3)
#ifndef BODAQS_SPI_BULK_BYTES
#define BODAQS_SPI_BULK_BYTES 0
#endif
#if BODAQS_SPI_BULK_BYTES
#if (BODAQS_SPI_BULK_BYTES != 512 && BODAQS_SPI_BULK_BYTES != 1024) || !BODAQS_SPI_MEASUREMENT_V4
#error "Bulk requires v4 window semantics and 512 or 1024 physical bytes"
#endif
#define BODAQS_MEASUREMENT_VERSION 5U
#define BODAQS_MEASUREMENT_BYTES BODAQS_SPI_BULK_BYTES
#define BODAQS_MEASUREMENT_BODY_BYTES (BODAQS_MEASUREMENT_BYTES-40U)
#define BODAQS_MEASUREMENT_HZ 16000000UL
#define BODAQS_MEASUREMENT_MAX_KIND 15U
#elif defined(BODAQS_SPI_MEASUREMENT_V4) && BODAQS_SPI_MEASUREMENT_V4
#define BODAQS_MEASUREMENT_VERSION 4U
#define BODAQS_MEASUREMENT_BYTES 256U
#define BODAQS_MEASUREMENT_BODY_BYTES 216U
#define BODAQS_MEASUREMENT_HZ 16000000UL
#define BODAQS_MEASUREMENT_MAX_KIND 15U
#elif defined(BODAQS_SPI_MEASUREMENT_V3) && BODAQS_SPI_MEASUREMENT_V3
#define BODAQS_MEASUREMENT_VERSION 3U
#define BODAQS_MEASUREMENT_BYTES 256U
#define BODAQS_MEASUREMENT_BODY_BYTES 216U
#define BODAQS_MEASUREMENT_HZ 16000000UL
#define BODAQS_MEASUREMENT_MAX_KIND 14U
#elif defined(BODAQS_SPI_MEASUREMENT_V2) && BODAQS_SPI_MEASUREMENT_V2
#define BODAQS_MEASUREMENT_VERSION 2U
#define BODAQS_MEASUREMENT_BYTES 256U
#define BODAQS_MEASUREMENT_BODY_BYTES 216U
#define BODAQS_MEASUREMENT_HZ 16000000UL
#define BODAQS_MEASUREMENT_MAX_KIND 14U
#else
#define BODAQS_MEASUREMENT_VERSION 1U
#define BODAQS_MEASUREMENT_BYTES 64U
#define BODAQS_MEASUREMENT_BODY_BYTES 40U
#define BODAQS_MEASUREMENT_HZ 8000000UL
#define BODAQS_MEASUREMENT_MAX_KIND 13U
#endif
#define BODAQS_SAMPLE_PAYLOADS ((BODAQS_MEASUREMENT_BODY_BYTES-20U)/64U)
#define BODAQS_SAMPLE_UNIT_MAX (20U+64U*BODAQS_SAMPLE_PAYLOADS)
#define BODAQS_SAMPLE_STORAGE_BYTES (BODAQS_MEASUREMENT_VERSION>=5?BODAQS_MEASUREMENT_BODY_BYTES:216U)
#define BODAQS_SAMPLE_RECORD_BYTES (44U+BODAQS_SAMPLE_STORAGE_BYTES)
/* Preserve the v3/v4 sample queue's payload RAM ceiling. */
#define BODAQS_SAMPLE_QUEUE_CAPACITY (66560U/BODAQS_SAMPLE_RECORD_BYTES)
#define BODAQS_MEASUREMENT_FRAGMENT_COUNT ((1024U+BODAQS_MEASUREMENT_BODY_BYTES-1U)/BODAQS_MEASUREMENT_BODY_BYTES)
#define BODAQS_MEASUREMENT_GAP_US 25U
#define BODAQS_MEASUREMENT_DEADLINE_MS 1000U
#define BODAQS_MODE_ENTRY 8U
#define BODAQS_MODE_EXIT 9U
#define BODAQS_MODE_INFO 10U
#define BODAQS_MODE_LEGACY 0U
#define BODAQS_MODE_ENTRY_PENDING 1U
#define BODAQS_MODE_ACTIVE 2U
#define BODAQS_MODE_EXIT_PENDING 3U
#define BODAQS_MODE_FAILED 4U
#define BODAQS_MODE_FLAG_ACTIVE 1U
#define BODAQS_MODE_FLAG_FENCED 2U
#define BODAQS_MODE_FLAG_CLEANUP 4U

typedef struct {
    uint8_t kind, node, index;
    uint64_t context;
    uint32_t object;
    uint16_t total;
    uint8_t body[BODAQS_MEASUREMENT_BODY_BYTES];
#if BODAQS_MEASUREMENT_VERSION >= 2
    uint32_t retiredObject,retiredChecksum;
    uint16_t retiredTotal,available;
    uint8_t retiredClass,retiredNode;
    bool retired;
#endif
} BodaqsMeasurementSlot;
typedef struct {
    uint64_t boot, session, recording, context, caller;
    uint16_t version, maximum, physical, reason, flags;
    uint8_t phase;
    uint32_t hz, gap;
} BodaqsMeasurementMode;
typedef struct {
    BodaqsMeasurementMode mode;
    uint32_t sequence, started_ms;
    bool quiescent, fenced;
} BodaqsMeasurementState;

static inline uint64_t bodaqs_measurement_get(const uint8_t *p, unsigned n) {
    uint64_t v = 0; unsigned i;
    for (i=0; i<n; ++i) v |= (uint64_t)p[i] << (8U*i);
    return v;
}
static inline void bodaqs_measurement_put(uint8_t *p, uint64_t v, unsigned n) {
    unsigned i; for(i=0;i<n;++i) p[i]=(uint8_t)(v>>(8U*i));
}
static inline bool bodaqs_measurement_zero(const uint8_t *p, unsigned n) {
    unsigned i; for(i=0;i<n;++i) if(p[i]) return false;
    return true;
}
/* Reflected CRC-32/ISO-HDLC, one byte at a time. The immutable table stays
 * in flash; callers retain the existing initial/final XOR and canonical bytes. */
#if defined(BODAQS_MASTER_CRC_RAM) && BODAQS_MASTER_CRC_RAM
#ifdef __cplusplus
extern "C" {
#endif
/* C-runtime initialized storage; all runtime consumers must only read. */
extern uint32_t bodaqs_master_crc_table[256];
#ifdef __cplusplus
}
#endif
#endif
static inline uint32_t bodaqs_measurement_crc_step(uint32_t c,uint8_t byte) {
#if defined(BODAQS_MASTER_CRC_RAM) && BODAQS_MASTER_CRC_RAM
    const uint32_t * const table=bodaqs_master_crc_table;
#else
    static const uint32_t table[256]={
#include "bodaqs_crc32_table_values.h"
    };
#endif
    return (c>>8)^table[(c^byte)&0xffU];
}
#ifndef BODAQS_MASTER_BLOCK_CRC
#define BODAQS_MASTER_BLOCK_CRC 0
#endif
#if BODAQS_MASTER_BLOCK_CRC != 0 && BODAQS_MASTER_BLOCK_CRC != 1
#error "BODAQS_MASTER_BLOCK_CRC must be 0 or 1"
#endif
#if BODAQS_MASTER_BLOCK_CRC
#include "bodaqs_crc32_blocks.h"
#endif
static inline uint32_t bodaqs_measurement_crc(const uint8_t *p, size_t n) {
#if BODAQS_MASTER_BLOCK_CRC
    return ~bodaqs_measurement_crc_update(0xffffffffU,p,n);
#else
    uint32_t c=0xffffffffU; size_t i;
    for(i=0;i<n;++i) c=bodaqs_measurement_crc_step(c,p[i]);
    return ~c;
#endif
}
static inline bool bodaqs_measurement_encode_extent(const BodaqsMeasurementSlot *s, uint8_t *p, size_t n, unsigned extent, unsigned body) {
    if(!s || !p || n<extent || s->kind>BODAQS_MEASUREMENT_MAX_KIND) return false;
    memset(p,0,extent); p[0]='B'; p[1]='M'; p[2]=BODAQS_MEASUREMENT_VERSION; p[3]=s->kind;
    bodaqs_measurement_put(p+4,s->context,8); bodaqs_measurement_put(p+12,s->object,4);
    p[16]=s->node; p[17]=s->index; bodaqs_measurement_put(p+18,s->total,2);
    memcpy(p+20,s->body,body);
#if BODAQS_MEASUREMENT_VERSION >= 2
    p[extent-20]=s->retiredClass;p[extent-19]=s->retiredNode;p[extent-18]=s->retired?1:0;
    bodaqs_measurement_put(p+extent-16,s->retiredObject,4);bodaqs_measurement_put(p+extent-12,s->retiredTotal,2);
    bodaqs_measurement_put(p+extent-10,s->available,2);bodaqs_measurement_put(p+extent-8,s->retiredChecksum,4);
#if BODAQS_SPI_BULK_BYTES
    p[extent-17]=BODAQS_MEASUREMENT_BYTES/512U;
#endif
#endif
    bodaqs_measurement_put(p+extent-4,bodaqs_measurement_crc(p,extent-4),4);
    return true;
}
static inline bool bodaqs_measurement_encode(const BodaqsMeasurementSlot *s,uint8_t *p,size_t n) {
    return bodaqs_measurement_encode_extent(s,p,n,BODAQS_MEASUREMENT_BYTES,BODAQS_MEASUREMENT_BODY_BYTES);
}
static inline bool bodaqs_measurement_encode_request(const BodaqsMeasurementSlot *s,uint8_t *p,size_t n) {
#if BODAQS_SPI_BULK_BYTES
    if(!s || s->retired || s->available || !bodaqs_measurement_zero(s->body+88,BODAQS_MEASUREMENT_BODY_BYTES-88)) return false;
    return bodaqs_measurement_encode_extent(s,p,n,128,88);
#else
    return bodaqs_measurement_encode(s,p,n);
#endif
}

typedef enum {
    BODAQS_MEASUREMENT_DECODE_OK=0, BODAQS_MEASUREMENT_DECODE_ARGUMENT,
    BODAQS_MEASUREMENT_DECODE_SIZE, BODAQS_MEASUREMENT_DECODE_MAGIC,
    BODAQS_MEASUREMENT_DECODE_VERSION, BODAQS_MEASUREMENT_DECODE_KIND,
    BODAQS_MEASUREMENT_DECODE_CRC, BODAQS_MEASUREMENT_DECODE_RESERVED,
    BODAQS_MEASUREMENT_DECODE_RETIRED_FLAG, BODAQS_MEASUREMENT_DECODE_AVAILABILITY,
    BODAQS_MEASUREMENT_DECODE_RETIREMENT, BODAQS_MEASUREMENT_DECODE_UNEXPECTED_RETIREMENT,
    BODAQS_MEASUREMENT_DECODE_PADDING, BODAQS_MEASUREMENT_DECODE_COUNT
} BodaqsMeasurementDecodeResult;
static inline const char *bodaqs_measurement_decode_name(BodaqsMeasurementDecodeResult result) {
    static const char *const names[]={"ok","argument","size","magic","version","kind","crc",
        "reserved","retired_flag","availability","retirement","unexpected_retirement","padding"};
    return (unsigned)result<BODAQS_MEASUREMENT_DECODE_COUNT?names[result]:"unknown";
}
/* First failed check, not a physical cause. Preserve the original bool API's
 * order and partial output semantics; callers must ignore rejected outputs. */
static inline BodaqsMeasurementDecodeResult bodaqs_measurement_decode_extent(const uint8_t *p,size_t n,BodaqsMeasurementSlot *s,unsigned extent,unsigned body) {
    if(!p || !s) return BODAQS_MEASUREMENT_DECODE_ARGUMENT;
    if(n!=extent) return BODAQS_MEASUREMENT_DECODE_SIZE;
    if(p[0]!='B' || p[1]!='M') return BODAQS_MEASUREMENT_DECODE_MAGIC;
    if(p[2]!=BODAQS_MEASUREMENT_VERSION) return BODAQS_MEASUREMENT_DECODE_VERSION;
    if(p[3]>BODAQS_MEASUREMENT_MAX_KIND) return BODAQS_MEASUREMENT_DECODE_KIND;
    if(bodaqs_measurement_crc(p,extent-4)!=bodaqs_measurement_get(p+extent-4,4)) return BODAQS_MEASUREMENT_DECODE_CRC;
    memset(s,0,sizeof(*s)); s->kind=p[3]; s->context=bodaqs_measurement_get(p+4,8);
    s->object=(uint32_t)bodaqs_measurement_get(p+12,4); s->node=p[16]; s->index=p[17];
    s->total=(uint16_t)bodaqs_measurement_get(p+18,2); memcpy(s->body,p+20,body);
#if BODAQS_MEASUREMENT_VERSION >= 2
    if(p[extent-17]!=(BODAQS_SPI_BULK_BYTES?BODAQS_MEASUREMENT_BYTES/512U:0)) return BODAQS_MEASUREMENT_DECODE_RESERVED;
    if(p[extent-18]>1) return BODAQS_MEASUREMENT_DECODE_RETIRED_FLAG;
    if(bodaqs_measurement_get(p+extent-10,2)&~255ULL) return BODAQS_MEASUREMENT_DECODE_AVAILABILITY;
    if(p[extent-18]) {
        if(p[extent-20]<1 || p[extent-20]>5 || (p[extent-20]==5?p[extent-19]!=255:p[extent-19]>3) ||
           !bodaqs_measurement_get(p+extent-16,4) || bodaqs_measurement_get(p+extent-12,2)<4 || bodaqs_measurement_get(p+extent-12,2)>1024) return BODAQS_MEASUREMENT_DECODE_RETIREMENT;
    } else if(!bodaqs_measurement_zero(p+extent-20,3) || !bodaqs_measurement_zero(p+extent-16,6) || !bodaqs_measurement_zero(p+extent-8,4)) return BODAQS_MEASUREMENT_DECODE_UNEXPECTED_RETIREMENT;
    s->retired=p[extent-18]!=0;s->retiredClass=p[extent-20];s->retiredNode=p[extent-19];
    s->retiredObject=(uint32_t)bodaqs_measurement_get(p+extent-16,4);s->retiredTotal=(uint16_t)bodaqs_measurement_get(p+extent-12,2);
    s->available=(uint16_t)bodaqs_measurement_get(p+extent-10,2);s->retiredChecksum=(uint32_t)bodaqs_measurement_get(p+extent-8,4);
    const unsigned padding=(BODAQS_MEASUREMENT_VERSION>=4 && s->kind==14)?48:40;
    if(s->kind!=2 && s->kind!=3 && s->kind!=4 && s->kind!=12 && s->kind!=13 &&
       !bodaqs_measurement_zero(s->body+padding,body-padding)) return BODAQS_MEASUREMENT_DECODE_PADDING;
#endif
    return BODAQS_MEASUREMENT_DECODE_OK;
}
static inline BodaqsMeasurementDecodeResult bodaqs_measurement_decode_result(const uint8_t *p,size_t n,BodaqsMeasurementSlot *s) {
    return bodaqs_measurement_decode_extent(p,n,s,BODAQS_MEASUREMENT_BYTES,BODAQS_MEASUREMENT_BODY_BYTES);
}
static inline bool bodaqs_measurement_decode_request(const uint8_t *p,size_t n,BodaqsMeasurementSlot *s) {
#if BODAQS_SPI_BULK_BYTES
    if(n!=BODAQS_MEASUREMENT_BYTES || bodaqs_measurement_decode_extent(p,128,s,128,88)!=BODAQS_MEASUREMENT_DECODE_OK) return false;
    return !s->retired && !s->available;
#else
    return bodaqs_measurement_decode_result(p,n,s)==BODAQS_MEASUREMENT_DECODE_OK;
#endif
}
static inline bool bodaqs_measurement_decode(const uint8_t *p,size_t n,BodaqsMeasurementSlot *s) {
    return bodaqs_measurement_decode_result(p,n,s)==BODAQS_MEASUREMENT_DECODE_OK;
}
static inline void bodaqs_measurement_mode_encode(const BodaqsMeasurementMode *m,uint8_t p[64]) {
    memset(p,0,64);
    bodaqs_measurement_put(p,m->boot,8); bodaqs_measurement_put(p+8,m->session,8);
    bodaqs_measurement_put(p+16,m->recording,8); bodaqs_measurement_put(p+24,m->context,8);
    bodaqs_measurement_put(p+32,m->version,2); bodaqs_measurement_put(p+34,m->maximum,2);
    bodaqs_measurement_put(p+36,m->physical,2); p[38]=m->phase;
    bodaqs_measurement_put(p+40,m->hz,4); bodaqs_measurement_put(p+44,m->gap,4);
    bodaqs_measurement_put(p+48,m->caller,8); bodaqs_measurement_put(p+56,m->reason,2);
    bodaqs_measurement_put(p+58,m->flags,2);
}
static inline bool bodaqs_measurement_mode_decode(const uint8_t *p,size_t n,BodaqsMeasurementMode *m) {
    if(!p || !m || n!=64 || p[39] || !bodaqs_measurement_zero(p+60,4)) return false;
    memset(m,0,sizeof(*m)); m->boot=bodaqs_measurement_get(p,8); m->session=bodaqs_measurement_get(p+8,8);
    m->recording=bodaqs_measurement_get(p+16,8); m->context=bodaqs_measurement_get(p+24,8);
    m->version=(uint16_t)bodaqs_measurement_get(p+32,2); m->maximum=(uint16_t)bodaqs_measurement_get(p+34,2);
    m->physical=(uint16_t)bodaqs_measurement_get(p+36,2); m->phase=p[38];
    m->hz=(uint32_t)bodaqs_measurement_get(p+40,4); m->gap=(uint32_t)bodaqs_measurement_get(p+44,4);
    m->caller=bodaqs_measurement_get(p+48,8); m->reason=(uint16_t)bodaqs_measurement_get(p+56,2);
    m->flags=(uint16_t)bodaqs_measurement_get(p+58,2); return true;
}
static inline bool bodaqs_measurement_limits(const BodaqsMeasurementMode *m) {
    return m->version==BODAQS_MEASUREMENT_VERSION && m->maximum==1024 && m->physical==BODAQS_MEASUREMENT_BYTES && m->hz==BODAQS_MEASUREMENT_HZ && m->gap==25;
}
static inline bool bodaqs_measurement_binding(const BodaqsMeasurementMode *a,const BodaqsMeasurementMode *b) {
    return a->boot==b->boot && a->session==b->session && a->recording==b->recording && a->context==b->context;
}
static inline void bodaqs_measurement_tick(BodaqsMeasurementState *s,uint32_t now) {
    if((s->mode.phase==1 || s->mode.phase==3) && (uint32_t)(now-s->started_ms)>=1000) {
        s->mode.phase=4; s->mode.reason=12;
    }
}
/* A stage is a reservation, never an acquisition grant. Failed transitions retain
 * identities, so retries cannot turn a lost acknowledgement into a new deadline. */
static inline uint16_t bodaqs_measurement_stage(BodaqsMeasurementState *s,const BodaqsMeasurementMode *r,
                                               uint32_t sequence,uint32_t now,bool exit_mode) {
    bodaqs_measurement_tick(s,now);
    if(!sequence || !r->boot || r->boot!=s->mode.boot || !r->session || r->caller!=r->session ||
       !r->recording || !r->context) return 4;
    if(!bodaqs_measurement_limits(r) || r->reason || r->flags) return 13;
    if(r->phase==1) return 0; /* observational inspection */
    if(r->phase!=2 && r->phase!=(exit_mode?3:0)) return 13;
    if(s->sequence==sequence && bodaqs_measurement_binding(&s->mode,r)) return s->mode.reason;
    if(!s->quiescent) return 10;
    if(!s->fenced) return 11;
    if(exit_mode || r->phase==2) {
        if(!bodaqs_measurement_binding(&s->mode,r)) return 4;
        if(s->mode.phase!=2 && s->mode.phase!=4 && s->mode.phase!=1) return 8;
    } else if(s->mode.phase!=0) return 8;
    if(r->phase==2) {
        if(!s->fenced) return 11;
        memset(&s->mode,0,sizeof(s->mode)); s->mode.boot=r->boot;
        s->sequence=sequence; return 0;
    }
    s->mode=*r; s->mode.phase=exit_mode?3:1; s->mode.reason=0;
    s->sequence=sequence; s->started_ms=now; return 0;
}
static inline void bodaqs_measurement_confirm_body(const BodaqsMeasurementMode *m,uint8_t p[40]) {
    memset(p,0,40); bodaqs_measurement_put(p,m->version,2); bodaqs_measurement_put(p+2,m->maximum,2);
    bodaqs_measurement_put(p+4,m->physical,2); bodaqs_measurement_put(p+8,m->gap,4); bodaqs_measurement_put(p+12,m->hz,4);
}
static inline bool bodaqs_measurement_manage(BodaqsMeasurementState *s,const BodaqsMeasurementSlot *r,
                                            uint32_t now,BodaqsMeasurementSlot *out) {
    uint8_t expected[40]; bodaqs_measurement_tick(s,now);
    if(r->node!=255 || r->index || r->total || !r->object) return false;
    if(r->kind==6) { if(!bodaqs_measurement_zero(r->body,40)) return false; }
    else if(r->kind==8 || r->kind==9) {
        bodaqs_measurement_confirm_body(&s->mode,expected);
        if(r->context!=s->mode.context || r->object!=s->sequence || memcmp(expected,r->body,40)) return false;
        if(r->kind==8 && s->mode.phase==1) { s->mode.phase=2; s->mode.flags=1; }
        else if(r->kind==9 && s->mode.phase==3 && s->quiescent && s->fenced) {
            s->mode.phase=0; s->mode.flags=2;
        } else if(!((r->kind==8 && s->mode.phase==2) || (r->kind==9 && s->mode.phase==0))) return false;
    } else return false;
    memset(out,0,sizeof(*out)); out->kind=6; out->node=255; out->object=r->object; out->context=r->context;
    bodaqs_measurement_put(out->body,s->mode.boot,8); bodaqs_measurement_put(out->body+8,s->mode.session,8);
    bodaqs_measurement_put(out->body+16,s->mode.recording,8); bodaqs_measurement_put(out->body+24,s->mode.context,8);
    out->body[32]=s->mode.phase; out->body[33]=(uint8_t)s->mode.reason;
    bodaqs_measurement_put(out->body+36,(s->mode.phase==2?1U:0U)|(s->fenced?2U:0U)|(!s->quiescent?4U:0U),4);
    return true;
}
#endif
