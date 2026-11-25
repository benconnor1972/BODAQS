/* Private v3 receipt plan: validate the whole message before releasing anything. */
typedef struct {uint32_t version,size_bytes;uint64_t context;uint32_t commands,sample_units,metadata_batches,reserved,base[4];} BpProgressInfo;
volatile BpProgressInfo gSampleProgressInfo __attribute__((section(".bodaqs_spi_buffers")));
_Static_assert(sizeof(BpProgressInfo)==48,"Sample progress diagnostic ABI");
static bool packed_progress_apply(BpMaster *p,BodaqsMasterService *s,const BpCommand *c,const uint8_t *raw,uint32_t now){
 BodaqsSampleWindowUnit *release[16];unsigned count=0;uint32_t bases[4];
 PackedAckPlan plans[BP_MAX_ACKS];bool fresh_metadata=c->count && c->metadata_sequence>p->metadata_sequence;
 if(c->count){
  if(c->metadata_sequence<p->metadata_sequence)return false;
  if(!fresh_metadata && (c->count!=p->metadata_count || memcmp(raw+56,p->metadata_wire,16*c->count)))return false;
  if(fresh_metadata){
   if(p->metadata_sequence==UINT32_MAX || c->metadata_sequence!=p->metadata_sequence+1)return false;
   for(unsigned i=0;i<c->count;++i){plans[i]=packed_ack_plan(s,&c->acks[i],p->context);if(!plans[i].action)return false;}
  }
 }
 for(unsigned n=0;n<4;++n){
  bases[n]=(uint32_t)bodaqs_measurement_get(c->sample_words+8*n,4);
  if(bases[n]<p->sample_base[n] || bases[n]-p->sample_base[n]>4 || bases[n]>UINT32_MAX-4 ||
     bases[n]>s->receptions[n].next_id[0]+1)return false;
  for(uint32_t id=p->sample_base[n];id<bases[n];++id){BodaqsSampleWindowUnit *u=&s->window->units[n][(id-1)%4];
   if(!u->object.complete){if(s->acquisition_fenced&(1U<<n))continue;return false;}
   if(u->object.object!=id || u->object.context!=p->context || u->object.node!=n || u->object.cls!=1 || !u->attempts)return false;
   release[count++]=u;
  }
 }
 for(unsigned i=0;i<count;++i){BodaqsSampleWindowUnit *u=release[i];
#if BODAQS_MASTER_PROGRESS_DIAGNOSTICS
  bodaqs_progress_retire(u->object.node,u,now);
#endif
  u->count=0;memset(&u->object,0,sizeof(u->object));++s->objects_acked;
 }
 // Existing bpm_prepare publication pass refills after this whole batch.
 for(unsigned n=0;n<4;++n){p->sample_base[n]=bases[n];gSampleProgressInfo.base[n]=bases[n];}
 if(fresh_metadata){for(unsigned i=0;i<c->count;++i)packed_ack_retire(s,&c->acks[i],&plans[i],now);
  p->metadata_sequence=c->metadata_sequence;p->metadata_count=c->count;memcpy(p->metadata_wire,raw+56,16*c->count);++gSampleProgressInfo.metadata_batches;
 }
 ++gSampleProgressInfo.commands;gSampleProgressInfo.sample_units+=count;return true;
}
