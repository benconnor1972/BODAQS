#ifndef BODAQS_SPI_TRACE_H
#define BODAQS_SPI_TRACE_H
#include "../protocol/bodaqs_measurement.h"
#include <stddef.h>

#define BODAQS_SPI_TRACE_CAPACITY 8U
#define BODAQS_SPI_TRACE_VERSION 1U
#define BODAQS_SPI_TRACE_BYTES 256U

/* Fixed32-bit scalar layout for exact debugger export; never a wire struct. */
typedef struct {
    uint32_t tick,epoch,stat,ctl0,ctl1;
    uint32_t tx_src,tx_dst,rx_src,rx_dst,tx_remaining,rx_remaining;
} BodaqsSpiTraceHardware;
typedef struct {
    uint32_t ordinal,length,source_address;
    BodaqsSpiTraceHardware arm,end;
    uint8_t tx_arm[256],tx_end[256],request[256];
} BodaqsSpiTraceEntry;
typedef struct {
    uint32_t version,bytes,capacity,count,next,ordinal;
    volatile uint32_t frozen;
    uint32_t overflow,boot_low,boot_high,context_low,context_high;
    uint32_t marker_ordinal,nonce,failed_device_sequence,logger_slot;
    uint32_t request_crc,reply_crc,arm_max_us,end_max_us;
    uint32_t source_address;
    BodaqsSpiTraceHardware armed;
    uint8_t tx_armed[256];
    BodaqsSpiTraceEntry entries[BODAQS_SPI_TRACE_CAPACITY];
} BodaqsSpiTrace;

static inline void bodaqs_spi_trace_init(BodaqsSpiTrace *t,uint64_t boot) {
    memset(t,0,sizeof(*t));t->version=1;t->bytes=sizeof(*t);t->capacity=8;
    t->boot_low=(uint32_t)boot;t->boot_high=(uint32_t)(boot>>32);
}
static inline void bodaqs_spi_trace_arm(BodaqsSpiTrace *t,const uint8_t *tx,
    uint32_t address,const BodaqsSpiTraceHardware *hardware) {
    if(t->frozen || t->overflow)return;
    t->source_address=address;t->armed=*hardware;memcpy(t->tx_armed,tx,256);
}
static inline bool bodaqs_spi_trace_marker(const uint8_t *rx,size_t length,
    BodaqsMeasurementSlot *marker) {
    if(length!=256 || rx[3]!=0 || memcmp(rx+20,"TRC8",4))return false;
    if(!bodaqs_measurement_decode(rx,length,marker))return false;
    return marker->kind==0 && marker->context && marker->object && marker->object!=UINT32_MAX &&
        marker->node==255 && !marker->index && !marker->total &&
        !marker->retired && !marker->available && marker->body[4]==1 &&
        bodaqs_measurement_zero(marker->body+5,3) &&
        bodaqs_measurement_get(marker->body+16,4)>0 &&
        bodaqs_measurement_get(marker->body+16,4)<UINT32_MAX &&
        bodaqs_measurement_get(marker->body+20,4)==marker->object &&
        bodaqs_measurement_zero(marker->body+24,BODAQS_MEASUREMENT_BODY_BYTES-24);
}
/* Returns marker-consumed, not a freeze acknowledgement. Hardware owner calls
 * this before rewriting/swapping selected buffers. Publication barrier is an
 * explicit adapter dependency; frozen is written last and never recycled. */
static inline bool bodaqs_spi_trace_end(BodaqsSpiTrace *t,const uint8_t *tx,
    const uint8_t *rx,size_t length,const BodaqsSpiTraceHardware *hardware,
    void (*barrier)(void)) {
    BodaqsMeasurementSlot marker;
    const bool tagged=bodaqs_spi_trace_marker(rx,length,&marker);
    if(t->frozen || t->overflow)return tagged;
    if(t->ordinal==UINT32_MAX) {t->overflow=1;return tagged;}
    ++t->ordinal;
    if(tagged) {
        t->context_low=(uint32_t)marker.context;t->context_high=(uint32_t)(marker.context>>32);
        t->marker_ordinal=t->ordinal;t->nonce=marker.object;t->logger_slot=marker.object;
        t->failed_device_sequence=(uint32_t)bodaqs_measurement_get(marker.body+16,4);
        t->request_crc=(uint32_t)bodaqs_measurement_get(marker.body+8,4);
        t->reply_crc=(uint32_t)bodaqs_measurement_get(marker.body+12,4);
        if(!barrier) {t->overflow=1;return true;}
        barrier();t->frozen=1;return true;
    }
    BodaqsSpiTraceEntry *e=&t->entries[t->next];
    e->ordinal=t->ordinal;e->length=(uint32_t)length;e->source_address=t->source_address;
    e->arm=t->armed;e->end=*hardware;
    memcpy(e->tx_arm,t->tx_armed,256);memcpy(e->tx_end,tx,256);memcpy(e->request,rx,256);
    t->next=(t->next+1)%8;if(t->count<8)++t->count;
    return false;
}
static inline void bodaqs_spi_trace_request(BodaqsMeasurementSlot *r,uint64_t context,
    uint32_t slot,uint32_t device_sequence,uint32_t request_crc,uint32_t reply_crc) {
    memset(r,0,sizeof(*r));r->context=context;r->object=slot;r->node=255;
    memcpy(r->body,"TRC8",4);r->body[4]=1;
    bodaqs_measurement_put(r->body+8,request_crc,4);bodaqs_measurement_put(r->body+12,reply_crc,4);
    bodaqs_measurement_put(r->body+16,device_sequence,4);bodaqs_measurement_put(r->body+20,slot,4);
}
#if defined(__cplusplus)
static_assert(sizeof(BodaqsSpiTraceEntry)==868,"Trace entry layout changed");
static_assert(sizeof(BodaqsSpiTrace)==7328,"Trace export layout changed");
static_assert(sizeof(BodaqsSpiTrace)<=8192,"Trace BANK1 budget exceeded");
#else
_Static_assert(sizeof(BodaqsSpiTraceEntry)==868,"Trace entry layout changed");
_Static_assert(sizeof(BodaqsSpiTrace)==7328,"Trace export layout changed");
_Static_assert(sizeof(BodaqsSpiTrace)<=8192,"Trace BANK1 budget exceeded");
#endif
#endif
