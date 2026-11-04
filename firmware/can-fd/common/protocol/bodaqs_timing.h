#ifndef BODAQS_TIMING_H
#define BODAQS_TIMING_H
#include "bodaqs_fragment_transport.h"
/* Class 6 has one physical slot in each direction. Its logical CRC uses the
 * same canonical context/object/node/class/direction/length prefix as objects. */
static inline uint32_t bodaqs_bridge_crc(const BodaqsMeasurementSlot *s,uint8_t direction) {
    BodaqsFragmentState f; memset(&f,0,sizeof(f));
    f.context=s->context;f.object=s->object;f.node=255;f.cls=6;
    f.direction=direction;f.total=direction?16:8;
    return bodaqs_fragment_checksum(&f,s->body);
}
static inline bool bodaqs_bridge_valid(const BodaqsMeasurementSlot *s,uint8_t direction) {
    unsigned n=direction?16:8;
    return s->kind==(direction?11:10) && s->context && s->object && s->node==255 &&
        !s->index && s->total==n && bodaqs_measurement_get(s->body,4)==s->object &&
        bodaqs_measurement_zero(s->body+n,40-n) &&
        bodaqs_measurement_get(s->body+n-4,4)==bodaqs_bridge_crc(s,direction);
}
static inline void bodaqs_bridge_request(BodaqsMeasurementSlot *s,uint64_t context,uint32_t token) {
    memset(s,0,sizeof(*s));s->kind=10;s->node=255;s->context=context;s->object=token;s->total=8;
    bodaqs_measurement_put(s->body,token,4);
    bodaqs_measurement_put(s->body+4,bodaqs_bridge_crc(s,0),4);
}
#endif

