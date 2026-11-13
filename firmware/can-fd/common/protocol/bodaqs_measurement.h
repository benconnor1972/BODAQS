#ifndef BODAQS_MEASUREMENT_H
#define BODAQS_MEASUREMENT_H
/* Canonical wire codec shared by the logger and master. No wire structs. */
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#define BODAQS_MEASUREMENT_CAPABILITY (1UL << 3)
#if defined(BODAQS_SPI_MEASUREMENT_V4) && BODAQS_SPI_MEASUREMENT_V4
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
static inline uint32_t bodaqs_measurement_crc_step(uint32_t c,uint8_t byte) {
    static const uint32_t table[256]={
        0x00000000U,0x77073096U,0xee0e612cU,0x990951baU,
        0x076dc419U,0x706af48fU,0xe963a535U,0x9e6495a3U,
        0x0edb8832U,0x79dcb8a4U,0xe0d5e91eU,0x97d2d988U,
        0x09b64c2bU,0x7eb17cbdU,0xe7b82d07U,0x90bf1d91U,
        0x1db71064U,0x6ab020f2U,0xf3b97148U,0x84be41deU,
        0x1adad47dU,0x6ddde4ebU,0xf4d4b551U,0x83d385c7U,
        0x136c9856U,0x646ba8c0U,0xfd62f97aU,0x8a65c9ecU,
        0x14015c4fU,0x63066cd9U,0xfa0f3d63U,0x8d080df5U,
        0x3b6e20c8U,0x4c69105eU,0xd56041e4U,0xa2677172U,
        0x3c03e4d1U,0x4b04d447U,0xd20d85fdU,0xa50ab56bU,
        0x35b5a8faU,0x42b2986cU,0xdbbbc9d6U,0xacbcf940U,
        0x32d86ce3U,0x45df5c75U,0xdcd60dcfU,0xabd13d59U,
        0x26d930acU,0x51de003aU,0xc8d75180U,0xbfd06116U,
        0x21b4f4b5U,0x56b3c423U,0xcfba9599U,0xb8bda50fU,
        0x2802b89eU,0x5f058808U,0xc60cd9b2U,0xb10be924U,
        0x2f6f7c87U,0x58684c11U,0xc1611dabU,0xb6662d3dU,
        0x76dc4190U,0x01db7106U,0x98d220bcU,0xefd5102aU,
        0x71b18589U,0x06b6b51fU,0x9fbfe4a5U,0xe8b8d433U,
        0x7807c9a2U,0x0f00f934U,0x9609a88eU,0xe10e9818U,
        0x7f6a0dbbU,0x086d3d2dU,0x91646c97U,0xe6635c01U,
        0x6b6b51f4U,0x1c6c6162U,0x856530d8U,0xf262004eU,
        0x6c0695edU,0x1b01a57bU,0x8208f4c1U,0xf50fc457U,
        0x65b0d9c6U,0x12b7e950U,0x8bbeb8eaU,0xfcb9887cU,
        0x62dd1ddfU,0x15da2d49U,0x8cd37cf3U,0xfbd44c65U,
        0x4db26158U,0x3ab551ceU,0xa3bc0074U,0xd4bb30e2U,
        0x4adfa541U,0x3dd895d7U,0xa4d1c46dU,0xd3d6f4fbU,
        0x4369e96aU,0x346ed9fcU,0xad678846U,0xda60b8d0U,
        0x44042d73U,0x33031de5U,0xaa0a4c5fU,0xdd0d7cc9U,
        0x5005713cU,0x270241aaU,0xbe0b1010U,0xc90c2086U,
        0x5768b525U,0x206f85b3U,0xb966d409U,0xce61e49fU,
        0x5edef90eU,0x29d9c998U,0xb0d09822U,0xc7d7a8b4U,
        0x59b33d17U,0x2eb40d81U,0xb7bd5c3bU,0xc0ba6cadU,
        0xedb88320U,0x9abfb3b6U,0x03b6e20cU,0x74b1d29aU,
        0xead54739U,0x9dd277afU,0x04db2615U,0x73dc1683U,
        0xe3630b12U,0x94643b84U,0x0d6d6a3eU,0x7a6a5aa8U,
        0xe40ecf0bU,0x9309ff9dU,0x0a00ae27U,0x7d079eb1U,
        0xf00f9344U,0x8708a3d2U,0x1e01f268U,0x6906c2feU,
        0xf762575dU,0x806567cbU,0x196c3671U,0x6e6b06e7U,
        0xfed41b76U,0x89d32be0U,0x10da7a5aU,0x67dd4accU,
        0xf9b9df6fU,0x8ebeeff9U,0x17b7be43U,0x60b08ed5U,
        0xd6d6a3e8U,0xa1d1937eU,0x38d8c2c4U,0x4fdff252U,
        0xd1bb67f1U,0xa6bc5767U,0x3fb506ddU,0x48b2364bU,
        0xd80d2bdaU,0xaf0a1b4cU,0x36034af6U,0x41047a60U,
        0xdf60efc3U,0xa867df55U,0x316e8eefU,0x4669be79U,
        0xcb61b38cU,0xbc66831aU,0x256fd2a0U,0x5268e236U,
        0xcc0c7795U,0xbb0b4703U,0x220216b9U,0x5505262fU,
        0xc5ba3bbeU,0xb2bd0b28U,0x2bb45a92U,0x5cb36a04U,
        0xc2d7ffa7U,0xb5d0cf31U,0x2cd99e8bU,0x5bdeae1dU,
        0x9b64c2b0U,0xec63f226U,0x756aa39cU,0x026d930aU,
        0x9c0906a9U,0xeb0e363fU,0x72076785U,0x05005713U,
        0x95bf4a82U,0xe2b87a14U,0x7bb12baeU,0x0cb61b38U,
        0x92d28e9bU,0xe5d5be0dU,0x7cdcefb7U,0x0bdbdf21U,
        0x86d3d2d4U,0xf1d4e242U,0x68ddb3f8U,0x1fda836eU,
        0x81be16cdU,0xf6b9265bU,0x6fb077e1U,0x18b74777U,
        0x88085ae6U,0xff0f6a70U,0x66063bcaU,0x11010b5cU,
        0x8f659effU,0xf862ae69U,0x616bffd3U,0x166ccf45U,
        0xa00ae278U,0xd70dd2eeU,0x4e048354U,0x3903b3c2U,
        0xa7672661U,0xd06016f7U,0x4969474dU,0x3e6e77dbU,
        0xaed16a4aU,0xd9d65adcU,0x40df0b66U,0x37d83bf0U,
        0xa9bcae53U,0xdebb9ec5U,0x47b2cf7fU,0x30b5ffe9U,
        0xbdbdf21cU,0xcabac28aU,0x53b39330U,0x24b4a3a6U,
        0xbad03605U,0xcdd70693U,0x54de5729U,0x23d967bfU,
        0xb3667a2eU,0xc4614ab8U,0x5d681b02U,0x2a6f2b94U,
        0xb40bbe37U,0xc30c8ea1U,0x5a05df1bU,0x2d02ef8dU,
    };
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
static inline bool bodaqs_measurement_encode(const BodaqsMeasurementSlot *s, uint8_t *p, size_t n) {
    if(!s || !p || n<BODAQS_MEASUREMENT_BYTES || s->kind>BODAQS_MEASUREMENT_MAX_KIND) return false;
    memset(p,0,BODAQS_MEASUREMENT_BYTES); p[0]='B'; p[1]='M'; p[2]=BODAQS_MEASUREMENT_VERSION; p[3]=s->kind;
    bodaqs_measurement_put(p+4,s->context,8); bodaqs_measurement_put(p+12,s->object,4);
    p[16]=s->node; p[17]=s->index; bodaqs_measurement_put(p+18,s->total,2);
    memcpy(p+20,s->body,BODAQS_MEASUREMENT_BODY_BYTES);
#if BODAQS_MEASUREMENT_VERSION >= 2
    p[236]=s->retiredClass;p[237]=s->retiredNode;p[238]=s->retired?1:0;
    bodaqs_measurement_put(p+240,s->retiredObject,4);bodaqs_measurement_put(p+244,s->retiredTotal,2);
    bodaqs_measurement_put(p+246,s->available,2);bodaqs_measurement_put(p+248,s->retiredChecksum,4);
#endif
    bodaqs_measurement_put(p+BODAQS_MEASUREMENT_BYTES-4,bodaqs_measurement_crc(p,BODAQS_MEASUREMENT_BYTES-4),4);
    return true;
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
static inline BodaqsMeasurementDecodeResult bodaqs_measurement_decode_result(const uint8_t *p,size_t n,BodaqsMeasurementSlot *s) {
    if(!p || !s) return BODAQS_MEASUREMENT_DECODE_ARGUMENT;
    if(n!=BODAQS_MEASUREMENT_BYTES) return BODAQS_MEASUREMENT_DECODE_SIZE;
    if(p[0]!='B' || p[1]!='M') return BODAQS_MEASUREMENT_DECODE_MAGIC;
    if(p[2]!=BODAQS_MEASUREMENT_VERSION) return BODAQS_MEASUREMENT_DECODE_VERSION;
    if(p[3]>BODAQS_MEASUREMENT_MAX_KIND) return BODAQS_MEASUREMENT_DECODE_KIND;
    if(bodaqs_measurement_crc(p,BODAQS_MEASUREMENT_BYTES-4)!=bodaqs_measurement_get(p+BODAQS_MEASUREMENT_BYTES-4,4)) return BODAQS_MEASUREMENT_DECODE_CRC;
    memset(s,0,sizeof(*s)); s->kind=p[3]; s->context=bodaqs_measurement_get(p+4,8);
    s->object=(uint32_t)bodaqs_measurement_get(p+12,4); s->node=p[16]; s->index=p[17];
    s->total=(uint16_t)bodaqs_measurement_get(p+18,2); memcpy(s->body,p+20,BODAQS_MEASUREMENT_BODY_BYTES);
#if BODAQS_MEASUREMENT_VERSION >= 2
    if(p[239]) return BODAQS_MEASUREMENT_DECODE_RESERVED;
    if(p[238]>1) return BODAQS_MEASUREMENT_DECODE_RETIRED_FLAG;
    if(bodaqs_measurement_get(p+246,2)&~255ULL) return BODAQS_MEASUREMENT_DECODE_AVAILABILITY;
    if(p[238]) {
        if(p[236]<1 || p[236]>5 || (p[236]==5?p[237]!=255:p[237]>3) ||
           !bodaqs_measurement_get(p+240,4) || bodaqs_measurement_get(p+244,2)<4 || bodaqs_measurement_get(p+244,2)>1024) return BODAQS_MEASUREMENT_DECODE_RETIREMENT;
    } else if(!bodaqs_measurement_zero(p+236,10) || !bodaqs_measurement_zero(p+248,4)) return BODAQS_MEASUREMENT_DECODE_UNEXPECTED_RETIREMENT;
    s->retired=p[238]!=0;s->retiredClass=p[236];s->retiredNode=p[237];
    s->retiredObject=(uint32_t)bodaqs_measurement_get(p+240,4);s->retiredTotal=(uint16_t)bodaqs_measurement_get(p+244,2);
    s->available=(uint16_t)bodaqs_measurement_get(p+246,2);s->retiredChecksum=(uint32_t)bodaqs_measurement_get(p+248,4);
    const unsigned padding=(BODAQS_MEASUREMENT_VERSION>=4 && s->kind==14)?48:40;
    if(s->kind!=2 && s->kind!=3 && s->kind!=4 && s->kind!=12 && s->kind!=13 &&
       !bodaqs_measurement_zero(s->body+padding,BODAQS_MEASUREMENT_BODY_BYTES-padding)) return BODAQS_MEASUREMENT_DECODE_PADDING;
#endif
    return BODAQS_MEASUREMENT_DECODE_OK;
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
