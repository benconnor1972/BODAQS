/* Diagnostic only. Main and boundary owners write disjoint record fields.
 * No protocol authority, allocation, logging, ISR CRC, or queue/pacing change. */
#include "packed_handoff_trace.h"
volatile PackedHandoffTrace gPackedHandoffTrace
 __attribute__((section(".bodaqs_spi_buffers"),aligned(8)));
static uint32_t gHandoffPhysical,gHandoffCurrent;
static uint16_t gHandoffReceive[BODAQS_MASTER_SPI_RX_CAPACITY],gHandoffTransmit[2];
static uint32_t handoff_tick(bool boundary) {
 uint32_t epoch;const uint32_t tick=bodaqs_master_timing_clock(NULL,&epoch);
 if(!epoch || epoch!=gPackedHandoffTrace.clock_epoch){
  if(boundary)gPackedHandoffTrace.isr_flags|=1;else gPackedHandoffTrace.main_flags|=1;
 }
 return tick;
}
static volatile PackedHandoffRecord *handoff_record(uint32_t token) {
 return token && token<=gPackedHandoffTrace.count?&gPackedHandoffTrace.records[token-1]:NULL;
}
static void handoff_arm(const uint8_t *wire,size_t length,bool valid) {
 if(!valid || length!=512 || memcmp(wire,"B51C",4) || gService.measurement.mode.phase!=2)return;
 if(!gPackedHandoffTrace.context){
  uint32_t mask=__get_PRIMASK();__disable_irq();
  gPackedHandoffTrace.version=1;gPackedHandoffTrace.size_bytes=sizeof gPackedHandoffTrace;
  gPackedHandoffTrace.context=gService.measurement.mode.context;
  gPackedHandoffTrace.recording=gService.transfer_recording;
  gPackedHandoffTrace.warmup_ms=gUptimeMs+20000U;
  __DMB();gPackedHandoffTrace.state=PH_WARMING;__set_PRIMASK(mask);
 }
 if(gPackedHandoffTrace.context!=gService.measurement.mode.context){gPackedHandoffTrace.main_flags|=2;return;}
 if(gPackedHandoffTrace.state==PH_WARMING && (int32_t)(gUptimeMs-gPackedHandoffTrace.warmup_ms)>=0){
  uint32_t epoch;bodaqs_master_timing_clock(NULL,&epoch);
  uint32_t mask=__get_PRIMASK();__disable_irq();
  gPackedHandoffTrace.clock_epoch=epoch;__DMB();gPackedHandoffTrace.state=PH_CAPTURING;__set_PRIMASK(mask);
 }
}
/* Called under the existing gSpiRetiring boundary serialization, before fence
 * rewriting or swapping the active TX. Headers here are observations, not CRC proof. */
static uint16_t handoff_boundary(const uint8_t *rx,const uint8_t *tx,size_t length,bool queued,uint16_t depth) {
 if(gHandoffPhysical==UINT32_MAX){gPackedHandoffTrace.isr_flags|=2;return 0;}
 ++gHandoffPhysical;
 if(gPackedHandoffTrace.state<PH_CAPTURING)return 0;
 uint32_t tick=0;const uint16_t source=gHandoffTransmit[gTransmitIndex];
 volatile PackedHandoffRecord *sent=handoff_record(source);
 if(sent && !sent->returned_tick && length==512 && !memcmp(tx,"B51P",4) &&
    bodaqs_measurement_get(tx+8,8)==gPackedHandoffTrace.context &&
    bodaqs_measurement_get(tx+16,4)==sent->prepared_sequence &&
    bodaqs_measurement_get(tx+24,4)==sent->prepared_confirm){
  tick=handoff_tick(true);sent->returned_tick=tick;sent->returned_physical=gHandoffPhysical;sent->flags|=PH_RETURNED;
 }
 if(gPackedHandoffTrace.state!=PH_CAPTURING)return 0;
 if(!tick)tick=handoff_tick(true);
 const uint32_t index=gPackedHandoffTrace.count;
 if(index>=PH_CAPACITY){gPackedHandoffTrace.isr_flags|=4;return 0;}
 volatile PackedHandoffRecord *r=&gPackedHandoffTrace.records[index];
 memset((void*)r,0,sizeof(*r));r->physical=gHandoffPhysical;r->cs_tick=tick;
 r->epoch=gPackedHandoffTrace.clock_epoch;r->depth=depth;
 if(length==512)r->flags|=PH_FULL;
 if(length==512 && !memcmp(rx,"B51C",4) && bodaqs_measurement_get(rx+8,8)==gPackedHandoffTrace.context){
  r->request_sequence=(uint32_t)bodaqs_measurement_get(rx+16,4);r->request_acks=rx[5];r->flags|=PH_COMMAND;
 }
 if(length==512 && !memcmp(tx,"B51P",4) && bodaqs_measurement_get(tx+8,8)==gPackedHandoffTrace.context){
  r->tx_sequence=(uint32_t)bodaqs_measurement_get(tx+16,4);r->tx_confirm=(uint32_t)bodaqs_measurement_get(tx+24,4);
 }
 r->flags|=queued?PH_QUEUED:PH_DROPPED;
 if(!index)gPackedHandoffTrace.first_physical=gHandoffPhysical;
 gPackedHandoffTrace.last_physical=gHandoffPhysical;
 __DMB();gPackedHandoffTrace.count=index+1;
 if(index+1==PH_CAPACITY)gPackedHandoffTrace.state=PH_FROZEN;
 return queued?(uint16_t)(index+1):0;
}
void bodaqs_master_handoff_accept(uint32_t command) {
 volatile PackedHandoffRecord *r=handoff_record(gHandoffCurrent);
 if(r && r->request_sequence==command){r->accept_tick=handoff_tick(false);r->main_flags|=PH_ACCEPTED;}
}
static void handoff_popped(void) {
 volatile PackedHandoffRecord *r=handoff_record(gHandoffCurrent);
 if(r){r->pop_tick=handoff_tick(false);r->main_flags|=PH_POPPED;}
}
static void handoff_prepared(const uint8_t *reply,bool valid) {
 volatile PackedHandoffRecord *r=handoff_record(gHandoffCurrent);
 if(r && valid){
  r->prepared_tick=handoff_tick(false);r->main_flags|=PH_VALID|PH_PREPARED;
  if(!memcmp(reply,"B51P",4)){
   r->prepared_sequence=(uint32_t)bodaqs_measurement_get(reply+16,4);
   r->prepared_confirm=(uint32_t)bodaqs_measurement_get(reply+24,4);
  }
 }
}
static void handoff_selected(unsigned index) {
 volatile PackedHandoffRecord *r=handoff_record(gHandoffTransmit[index]);
 if(r && !r->selected_tick){r->selected_tick=handoff_tick(true);r->flags|=PH_SELECTED;}
}
