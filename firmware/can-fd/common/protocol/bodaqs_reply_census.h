#ifndef BODAQS_REPLY_CENSUS_H
#define BODAQS_REPLY_CENSUS_H
#ifndef BODAQS_MASTER_REPLY_CENSUS
#define BODAQS_MASTER_REPLY_CENSUS 0
#endif
#if BODAQS_MASTER_REPLY_CENSUS != 0 && BODAQS_MASTER_REPLY_CENSUS != 1
#error "Reply census must be zero or one"
#endif
#if BODAQS_MASTER_REPLY_CENSUS
#if !BODAQS_MASTER_PROGRESS_DIAGNOSTICS || !BODAQS_MASTER_PHASE_TIMING
#error "Reply census requires the existing scoped master progress/phase diagnostics"
#endif
/* Main-owner observation of PREPARED replies, not physical receipt. */
typedef struct {
    uint32_t version,size_bytes,state,reserved;
    uint64_t context,recording;
    uint32_t kinds[16],errors[16],new_class[6],repeat_class[6],fragment_bytes[16];
    uint32_t evidence_types[6],control_opcodes[2][16];
    uint32_t seen_object[6][4][4];
} BodaqsReplyCensus;
extern volatile BodaqsReplyCensus gMasterReplyCensus;
static inline void bodaqs_reply_census_reset(uint64_t context,uint64_t recording){
    memset((void*)&gMasterReplyCensus,0,sizeof gMasterReplyCensus);
    gMasterReplyCensus.version=1;gMasterReplyCensus.size_bytes=sizeof gMasterReplyCensus;
    gMasterReplyCensus.context=context;gMasterReplyCensus.recording=recording;
}
static inline void bodaqs_reply_census_record(const BodaqsMeasurementSlot *reply){
    if(reply->kind>=16)return;
    ++gMasterReplyCensus.kinds[reply->kind];
    if(reply->kind==7 && reply->body[1]<16)++gMasterReplyCensus.errors[reply->body[1]];
    const uint8_t cls=bodaqs_fragment_class(reply->kind);
    if(!cls)return;
    const unsigned node=reply->node<4?reply->node:0;
    const unsigned offset=reply->index*BODAQS_MEASUREMENT_BODY_BYTES;
    if(offset<reply->total){unsigned count=reply->total-offset;if(count>BODAQS_MEASUREMENT_BODY_BYTES)count=BODAQS_MEASUREMENT_BODY_BYTES;gMasterReplyCensus.fragment_bytes[reply->kind]+=count;}
    if(!reply->index){
        volatile uint32_t *seen=&gMasterReplyCensus.seen_object[cls][node][reply->object%4];
        if(*seen==reply->object){++gMasterReplyCensus.repeat_class[cls];return;}
        *seen=reply->object;++gMasterReplyCensus.new_class[cls];
        if(cls==2){
            const uint16_t id=(uint16_t)bodaqs_measurement_get(reply->body+16,2);
            const uint8_t type=reply->body[29];
            ++gMasterReplyCensus.evidence_types[(id==0x90U+reply->node && type>=0x21 && type<=0x25)?type-0x21:5];
        }
        if((cls==3 || cls==4) && reply->body[12]>=0x20 && reply->body[12]<0x30)
            ++gMasterReplyCensus.control_opcodes[cls-3][reply->body[12]-0x20];
    }
}
#endif
#endif
