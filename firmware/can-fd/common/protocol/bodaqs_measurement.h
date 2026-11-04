#ifndef BODAQS_MEASUREMENT_H
#define BODAQS_MEASUREMENT_H
/* Canonical wire codec shared by the logger and master. No wire structs. */
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#define BODAQS_MEASUREMENT_CAPABILITY (1UL << 3)
#define BODAQS_MEASUREMENT_BYTES 64U
#define BODAQS_MEASUREMENT_HZ 8000000UL
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
    uint8_t body[40];
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
static inline uint32_t bodaqs_measurement_crc(const uint8_t *p, size_t n) {
    uint32_t c=0xffffffffU; size_t i; unsigned b;
    for(i=0;i<n;++i) { c^=p[i]; for(b=0;b<8;++b) c=(c>>1)^(0xedb88320U & (0U-(c&1U))); }
    return ~c;
}
static inline bool bodaqs_measurement_encode(const BodaqsMeasurementSlot *s, uint8_t *p, size_t n) {
    if(!s || !p || n<64 || s->kind>13) return false;
    memset(p,0,64); p[0]='B'; p[1]='M'; p[2]=1; p[3]=s->kind;
    bodaqs_measurement_put(p+4,s->context,8); bodaqs_measurement_put(p+12,s->object,4);
    p[16]=s->node; p[17]=s->index; bodaqs_measurement_put(p+18,s->total,2);
    memcpy(p+20,s->body,40); bodaqs_measurement_put(p+60,bodaqs_measurement_crc(p,60),4);
    return true;
}
static inline bool bodaqs_measurement_decode(const uint8_t *p,size_t n,BodaqsMeasurementSlot *s) {
    if(!p || !s || n!=64 || p[0]!='B' || p[1]!='M' || p[2]!=1 || p[3]>13 ||
       bodaqs_measurement_crc(p,60)!=bodaqs_measurement_get(p+60,4)) return false;
    memset(s,0,sizeof(*s)); s->kind=p[3]; s->context=bodaqs_measurement_get(p+4,8);
    s->object=(uint32_t)bodaqs_measurement_get(p+12,4); s->node=p[16]; s->index=p[17];
    s->total=(uint16_t)bodaqs_measurement_get(p+18,2); memcpy(s->body,p+20,40); return true;
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
    return m->version==1 && m->maximum==1024 && m->physical==64 && m->hz==8000000UL && m->gap==25;
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
