#include "packed_master.h"
#if defined(BODAQS_PACKED_HANDOFF_TRACE) && BODAQS_PACKED_HANDOFF_TRACE
extern void bodaqs_master_handoff_accept(uint32_t command);
#endif
/* Private decoded-command seam. bp_command_decode has checked CRC, shape,
 * disposition, duplicate identities and reserved bytes before these helpers.
 * Match the same retained identity as a legacy ACK without synthesizing its
 * large zero-padded wire slot. Only the main owner mutates retained objects. */
typedef struct {
 BodaqsFragmentState *state;
 unsigned action,unit; /* 0 invalid, 1 live, 2 cached at validation snapshot */
} PackedAckPlan;
static bool packed_ack_matches(const BodaqsFragmentState *state,const BpAck *a,uint64_t context) {
 return state->complete && state->context==context && state->object==a->object &&
  state->node==a->node && state->cls==a->cls && state->total==a->total && state->checksum==a->checksum;
}
static PackedAckPlan packed_ack_plan(BodaqsMasterService *s,const BpAck *a,uint64_t context) {
 PackedAckPlan plan={0};const unsigned cls=a->cls,node=cls==5?0:a->node;
 if(packed_ack_matches(&s->acknowledged[cls-1][node],a,context)){plan.action=2;return plan;}
 if(cls==1) {
  for(unsigned i=0;i<BODAQS_SAMPLE_WINDOW;++i) {
   BodaqsSampleWindowUnit *u=&s->window->units[node][i];
   if(packed_ack_matches(&u->acknowledged,a,context)){plan.action=2;return plan;}
   if(packed_ack_matches(&u->object,a,context)){plan.state=&u->object;plan.action=1;plan.unit=i;return plan;}
  }
 } else {
  plan.state=cls==2?&s->receptions[node].object:cls<5?&s->lanes[cls-3][node].tx:&s->master_evidence;
  if(packed_ack_matches(plan.state,a,context))plan.action=1;
 }
 return plan;
}
static void packed_ack_retire(BodaqsMasterService *s,const BpAck *a,const PackedAckPlan *plan,uint32_t now) {
 /* The complete vector was validated before any release. A cached entry stays
  * a no-op even if an earlier live release replaces that retirement cache.
  * Other live entries remain pinned through refills; no unit can be reused
  * before its own release. Preserve legacy retirement/refill ordering exactly. */
 if(plan->action==2)return;
 const unsigned cls=a->cls,node=cls==5?0:a->node;
 if(cls==1) {
  BodaqsSampleWindowUnit *u=&s->window->units[node][plan->unit];
#if BODAQS_MASTER_PROGRESS_DIAGNOSTICS
  bodaqs_progress_retire(node,u,now);
#endif
  u->acknowledged=*plan->state;u->count=0;memset(plan->state,0,sizeof(*plan->state));
  ++s->objects_acked;advance_receptions(s,node,now);return;
 }
 if(cls==2) {
#if BODAQS_MASTER_BATCH_DIAGNOSTICS
  bodaqs_batch_diag_retire(node,cls,now);
#endif
  s->acknowledged[cls-1][node]=*plan->state;s->receptions[node].count=0;
  memset(plan->state,0,sizeof(*plan->state));advance_receptions(s,node,now);
 } else {
  s->acknowledged[cls-1][node]=*plan->state;plan->state->complete=0;
 }
 ++s->objects_acked;
}
#if BODAQS_PACKED_PROGRESS
#include "packed_progress_master.inc"
#endif
bool bpm_init(BpMaster *p,BodaqsMasterService *s,bool selected) {
 if(!p || !s || !selected || !s->window || s->measurement.mode.phase!=2 ||
    !s->measurement.mode.context || s->transfer_context!=s->measurement.mode.context) return false;
 memset(p,0,sizeof(*p));p->context=s->transfer_context;
#if BODAQS_PACKED_PROGRESS
 for(unsigned n=0;n<4;++n)p->sample_base[n]=1;
 memset((void*)&gSampleProgressInfo,0,sizeof gSampleProgressInfo);
 gSampleProgressInfo.version=1;gSampleProgressInfo.size_bytes=sizeof gSampleProgressInfo;gSampleProgressInfo.context=p->context;
 for(unsigned n=0;n<4;++n)gSampleProgressInfo.base[n]=1;
#endif
 return true;
}
static bool bound(BpMaster *p,BodaqsMasterService *s,unsigned slot) {
 return p && s && slot<2 && !p->slots[slot].owned && p->slots[slot].generation!=UINT32_MAX &&
  p->physical!=UINT32_MAX && s->measurement.mode.phase==2 && p->context &&
  p->context==s->measurement.mode.context && s->window && p->context==s->transfer_context;
}
static bool add(BpReply *reply,const BodaqsFragmentState *state,const uint8_t *body) {
 if(!state->complete || state->total>468 || reply->count==4)return false;
 unsigned used=0;for(unsigned i=0;i<reply->count;++i)used+=8+reply->items[i].length;
 if(used+8+state->total>476)return false;
 reply->items[reply->count++]=(BpItem){body,state->object,state->total,bodaqs_fragment_kind(state->cls),state->node};return true;
}
/* One cursor over all retained metadata lanes: protected, ordinary, evidence,
 * shared. At least one fair selection precedes the extra protected preference.
 * A head that does not fit remains first for the next metadata opportunity. */
static void metadata_lane(BodaqsMasterService *s,unsigned lane,
 const BodaqsFragmentState **state,const uint8_t **bytes) {
 if(lane<8){unsigned cls=lane<4?4:3,n=lane%4;
  *state=&s->lanes[cls-3][n].tx;*bytes=s->lanes[cls-3][n].outgoing;
 }else if(lane<12){*state=&s->receptions[lane-8].object;*bytes=s->receptions[lane-8].bytes;}
 else {*state=&s->master_evidence;*bytes=s->master_evidence_bytes;}
}
static bool metadata_fair(BpMaster *p,BodaqsMasterService *s,BpReply *reply,bool selected[13]) {
 for(unsigned step=0;step<13;++step){
  unsigned lane=p->node;const BodaqsFragmentState *state;const uint8_t *bytes;
  metadata_lane(s,lane,&state,&bytes);
  if(!selected[lane] && state->complete && state->total<=468){
   if(!add(reply,state,bytes))return false;
   selected[lane]=true;p->node=(uint8_t)((lane+1)%13);return true;
  }
  p->node=(uint8_t)((lane+1)%13);
 }
 return false;
}
bool bpm_prepare(BpMaster *p,BodaqsMasterService *s,const uint8_t raw[BP_COMMAND_BYTES],uint32_t now,unsigned index,uint32_t *generation) {
 if(!raw || !generation || !bound(p,s,index))return false;
 /* Exact bytes of the last accepted command already passed codec/credit
  * validation. Reuse that proof only inside the bound live context. A retry
  * must still perform normal maintenance/publication, never retire ACKs twice. */
 const bool exact_retry=p->command && !memcmp(raw,p->last_command,BP_COMMAND_BYTES);
 if(!exact_retry) {
 BpCommand c;
 if(!bp_command_decode(raw,BP_COMMAND_BYTES,p->context,&c) || !window_request_valid(c.sample_words))return false;
 if(c.sequence==p->command && memcmp(raw,p->last_command,BP_COMMAND_BYTES))return false;
 if(c.sequence>p->command) {
#if BODAQS_PACKED_PROGRESS
  if(!packed_progress_apply(p,s,&c,raw,now))return false;
#else
  /* No retirement, queue advance or credit mutation before the FULL vector is known. */
  PackedAckPlan plans[BP_MAX_ACKS];
  for(unsigned i=0;i<c.count;++i){plans[i]=packed_ack_plan(s,&c.acks[i],p->context);if(!plans[i].action)return false;}
  for(unsigned i=0;i<c.count;++i)packed_ack_retire(s,&c.acks[i],&plans[i],now);
  #endif
  p->command=c.sequence;memcpy(p->last_command,raw,BP_COMMAND_BYTES);
#if defined(BODAQS_PACKED_HANDOFF_TRACE) && BODAQS_PACKED_HANDOFF_TRACE
  bodaqs_master_handoff_accept(p->command);
#endif
 }
 }
 /* Older commands cannot reopen old grants. Resends of the exact current
  * command remain idempotent even after its objects have been recycled. */
 const uint8_t *credits=p->last_command+24;
 BpReply reply={0};reply.context=p->context;reply.sequence=p->physical+1;reply.confirmed_command=p->command;
#if BODAQS_PACKED_PROGRESS
 reply.confirmed_metadata=p->metadata_sequence;
#endif
 /* Preserve source-loss reporting and control-result formation through the
  * actual r49 logic. Returned non-retained diagnostics use the legacy escape;
  * retained heads are then eligible for compound packing. */
 BodaqsMeasurementSlot maintenance={0},observed={0};maintenance.context=p->context;
 maintenance.kind=1;maintenance.node=(p->turn/2)%4;maintenance.body[0]=3+(p->turn%2);
 if(!measurement_transfer_core(s,&maintenance,now,&observed))return false;
 if(observed.kind==7){if(!bodaqs_measurement_encode(&observed,p->slots[index].wire,512))return false;++p->turn;goto published;}
 memset(&maintenance,0,sizeof maintenance);maintenance.context=p->context;maintenance.kind=1;maintenance.node=255;maintenance.body[0]=1;
 if(!measurement_transfer_core(s,&maintenance,now,&observed))return false;
 if(observed.kind==7){if(!bodaqs_measurement_encode(&observed,p->slots[index].wire,512))return false;++p->turn;goto published;}
 for(unsigned n=0;n<4;++n)window_advance(s,n,now);
 /* Seven sample opportunities per metadata opportunity. Always use only
  * currently published heads; no batch-fill sleep or new queue allocation. */
 const bool metadata=p->turn%8==7;
 if(!metadata){
#if BODAQS_PACKED_SAMPLE_VIEW
  /* Published unit bytes remain main-owner retained. The view exists only
   * through this synchronous encode; the physical slot gets its own copy.
   * Shared selection preserves fairness, repair accounting and advancement. */
  const BodaqsSampleWindowUnit *sample=window_select(s,credits,now);
  if(sample) {
   reply.items[reply.count++]=(BpItem){sample->bytes,sample->object.object,sample->object.total,
       bodaqs_fragment_kind(sample->object.cls),sample->object.node};
  }
#else
  BodaqsMeasurementSlot sample={};if(window_emit(s,credits,now,&sample)) {
  reply.items[reply.count++]=(BpItem){sample.body,sample.object,sample.total,sample.kind,sample.node}; }
#endif
  /* sample.body is stack storage; encode while it is still live below. */
  if(reply.count){bool ok=bp_encode(&reply,p->slots[index].wire);if(!ok)return false;
   ++p->turn;goto published;}}
 {
  bool selected[13]={false};
  (void)metadata_fair(p,s,&reply,selected);
  for(unsigned turn=0;turn<4 && reply.count<4;++turn){
   unsigned n=(p->node+turn)%4;
   if(!selected[n] && add(&reply,&s->lanes[1][n].tx,s->lanes[1][n].outgoing)){
    selected[n]=true;break;
   }
  }
  while(reply.count<4 && metadata_fair(p,s,&reply,selected)){}
 }
 if(!bp_encode(&reply,p->slots[index].wire))return false;
 ++p->turn;
published:
 ++p->physical;*generation=++p->slots[index].generation;p->slots[index].owned=true;return true;
}
bool bpm_legacy(BpMaster *p,BodaqsMasterService *s,const uint8_t *raw,size_t bytes,uint32_t now,unsigned index,uint32_t *generation) {
 if(!generation || !bound(p,s,index))return false;
 if(bodaqs_master_service_process_transfer_legacy(s,raw,bytes,now,p->slots[index].wire)!=BODAQS_MASTER_SLOT_PROCESSED)return false;
 ++p->physical;*generation=++p->slots[index].generation;p->slots[index].owned=true;return true;
}
bool bpm_retire(BpMaster *p,unsigned index,uint32_t gen,bool full,bool cs) {
 if(!p || index>=2 || !p->slots[index].owned || p->slots[index].generation!=gen || !full || !cs)return false;
 p->slots[index].owned=false;return true;
}

