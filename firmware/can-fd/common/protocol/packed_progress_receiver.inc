/* Version3: sample custody is cumulative and independent of exact metadata.
 * Single acquisition owner; no pointer to physical RX bytes escapes this call. */
static unsigned cell_index(unsigned cls,unsigned node,uint32_t object) {
 return cls==1?4*node+(object-1)%4:cls==5?28:16+4*(cls-2)+node;
}
bool bpr_init(BpReceiver *r,uint64_t context,bool selected) {
 if(!r || !context || !selected)return false;
#if defined(BODAQS_PACKED_SEGMENTED_RECEIVER) && BODAQS_PACKED_SEGMENTED_RECEIVER
 uint8_t *storage[29];for(unsigned i=0;i<29;++i){storage[i]=r->cells[i].bytes;if(!storage[i])return false;}
#endif
 memset(r,0,sizeof(*r));
#if defined(BODAQS_PACKED_SEGMENTED_RECEIVER) && BODAQS_PACKED_SEGMENTED_RECEIVER
 for(unsigned i=0;i<29;++i){r->cells[i].bytes=storage[i];memset(storage[i],0,468);}
#endif
 r->context=context;for(unsigned n=0;n<4;++n){r->base[n]=r->next[n]=1;bodaqs_measurement_put(r->sample_words+8*n,1,4);}
 r->samples_dirty=r->metadata_dirty=true;return true;
}
void bpr_pump(BpReceiver *r,BpAdmit admit,void *arg) {
 if(!r || r->exhausted || !admit)return;
 for(unsigned i=0;i<29;++i){BpReceiverCell *c=&r->cells[i];
  if(c->state.complete && !c->admitted && !c->retired &&
     (c->state.cls!=1 || c->state.object==r->next[c->state.node]) &&
     admit(arg,bodaqs_fragment_kind(c->state.cls),c->state.node,c->state.object,c->bytes,c->state.total)) {
   c->admitted=true;if(c->state.cls==1)++r->next[c->state.node];else r->metadata_dirty=true;
  }
 }
 for(unsigned n=0;n<4;++n)while(r->base[n]<r->next[n]){
  BpReceiverCell *c=&r->cells[cell_index(1,n,r->base[n])];
  if(!c->admitted || c->state.object!=r->base[n] || r->base[n]>=UINT32_MAX-4){r->exhausted=true;return;}
  c->confirmed=c->state.object;c->state.object=0;c->state.complete=false;c->admitted=c->retired=false;
  ++r->base[n];++r->custody_units[n];++r->pending_custody;
  bodaqs_measurement_put(r->sample_words+8*n,r->base[n],4);
  r->sample_words[8*n+4]>>=1;r->samples_dirty=true;
 }
}
static bool confirm_metadata(BpReceiver *r,uint32_t sequence,BpConfirmed notify,void *arg) {
 if(sequence>r->metadata_sequence)return false;
 if(!r->awaiting || sequence!=r->inflight.metadata_sequence)return true;
 for(unsigned i=0;i<r->inflight.count;++i){const BpAck *a=&r->inflight.acks[i];
  const BpReceiverCell *c=&r->cells[cell_index(a->cls,a->node,a->object)];
  if(c->state.object!=a->object || c->state.checksum!=a->checksum || !c->admitted){r->exhausted=true;return false;}
 }
 for(unsigned i=0;i<r->inflight.count;++i){const BpAck *a=&r->inflight.acks[i];
  BpReceiverCell *c=&r->cells[cell_index(a->cls,a->node,a->object)];
  c->confirmed=a->object;c->retired=true;c->state.object=0;c->state.complete=false;c->admitted=false;
  if(notify)notify(arg,a);
 }
 r->awaiting=false;r->metadata_dirty=true;return true;
}
bool bpr_receive_decoded_notify(BpReceiver *r,const BpReply *reply,BpAdmit admit,void *arg,BpConfirmed notify,void *notification_arg){
 if(!r || r->exhausted || !reply || reply->context!=r->context || reply->confirmed_command>r->sequence ||
    !confirm_metadata(r,reply->confirmed_metadata,notify,notification_arg))return false;
 for(unsigned i=0;i<reply->count;++i){const BpItem *item=&reply->items[i];unsigned cls=bodaqs_fragment_class(item->kind);
  if(cls==1 && item->object<r->base[item->node])continue;
  if(cls==1 && item->object-r->base[item->node]>=4){++r->rejected;continue;}
  BpReceiverCell *c=&r->cells[cell_index(cls,item->node,item->object)];
  if(cls!=1 && item->object<=c->confirmed)continue;
  if(c->state.object && c->state.object!=item->object){++r->rejected;continue;}
  if(!c->state.object)c->retired=false;
  const bool was_complete=c->state.complete;
  const BodaqsFragmentView view={item->body,r->context,item->object,item->length,item->length,item->node,item->kind,0};
  if(bodaqs_fragment_accept_view(&c->state,c->bytes,468,&view,1,NULL)<1)++r->rejected;
  else if(cls==1 && !was_complete){
   r->sample_words[8*item->node+4]|=(uint8_t)(1U<<(item->object-r->base[item->node]));r->samples_dirty=true;
  }
 }
 bpr_pump(r,admit,arg);return !r->exhausted;
}
bool bpr_receive_decoded(BpReceiver *r,const BpReply *reply,BpAdmit admit,void *arg){return bpr_receive_decoded_notify(r,reply,admit,arg,NULL,NULL);}
bool bpr_receive(BpReceiver *r,const uint8_t wire[512],BpAdmit admit,void *arg){
 BpReply reply;if(!r || !bp_decode(wire,512,r->context,&reply))return false;
 return bpr_receive_decoded(r,&reply,admit,arg);
}
bool bpr_command_at(BpReceiver *r,uint8_t wire[BP_COMMAND_BYTES],uint32_t now_us,bool force){
 if(!r || r->exhausted || !wire)return false;
 if(r->sequence && !r->samples_dirty && !(r->metadata_dirty && !r->awaiting)){
  ++r->unchanged_commands;memcpy(wire,r->command_wire,BP_COMMAND_BYTES);return true;
 }
 if(!r->awaiting && r->metadata_dirty){
  BpCommand next={0};next.context=r->context;
  unsigned protected_index=29;
  for(unsigned step=0;step<4;++step){unsigned n=(r->protected_cursor+step)%4;const BpReceiverCell *c=&r->cells[24+n];
   if(c->admitted && !c->retired){next.acks[next.count++]=(BpAck){c->state.object,c->state.checksum,c->state.total,c->state.node,c->state.cls,1};
    protected_index=24+n;r->protected_cursor=(uint8_t)((n+1)%4);break;}
  }
  unsigned start=r->ack_cursor;
  for(unsigned step=0;step<13 && next.count<BP_MAX_ACKS;++step){unsigned i=16+(start+step)%13;const BpReceiverCell *c=&r->cells[i];
   if(i!=protected_index && c->admitted && !c->retired){next.acks[next.count++]=(BpAck){c->state.object,c->state.checksum,c->state.total,c->state.node,c->state.cls,1};r->ack_cursor=(uint8_t)((i-16+1)%13);}
  }
  if(next.count){if(r->metadata_sequence==UINT32_MAX){r->exhausted=true;return false;}next.metadata_sequence=++r->metadata_sequence;r->awaiting=true;}
  r->inflight=next;r->metadata_dirty=false;
 }
 const bool metadata_changed=!r->sequence || r->command_wire[5]!=r->inflight.count ||
     bodaqs_measurement_get(r->command_wire+20,4)!=r->inflight.metadata_sequence;
 if(!metadata_changed && !r->samples_dirty){
  ++r->unchanged_commands;memcpy(wire,r->command_wire,BP_COMMAND_BYTES);return true;
 }
 if(r->sequence==UINT32_MAX){r->exhausted=true;return false;}
#if BODAQS_PACKED_PROGRESS_BATCH
 /* A held head must suppress repair immediately, even under backpressure.
  * Only a single already-admitted receipt may wait; two units flush together. */
 const bool held=r->sample_words[4] || r->sample_words[12] || r->sample_words[20] || r->sample_words[28];
 if(!metadata_changed && !force && r->pending_custody==1 && !held){
  if(!r->progress_timer){r->progress_started_us=now_us;r->progress_timer=true;}
  if((uint32_t)(now_us-r->progress_started_us)<4000){
   ++r->coalesced_commands;memcpy(wire,r->command_wire,BP_COMMAND_BYTES);return true;
  }
 }
#else
 (void)force;
#endif
 if(r->progress_timer){uint32_t hold=(uint32_t)(now_us-r->progress_started_us);
  if(hold>r->progress_hold_max_us)r->progress_hold_max_us=hold;
 }
 const uint32_t sequence=++r->sequence;
#if BODAQS_PACKED_COMMAND_TEMPLATE
 if(!metadata_changed) {
  /* The owned cache passed the full encoder in this context. Only sequence
   * and canonical sample words changed; retain exact metadata/reserved bytes.
   * Recompute the same full command CRC, never a shortened checksum. */
  bodaqs_measurement_put(r->command_wire+16,sequence,4);
  memcpy(r->command_wire+24,r->sample_words,32);
  bodaqs_measurement_put(r->command_wire+252,bodaqs_measurement_crc(r->command_wire,252),4);
 } else
#endif
 {
  BpCommand c=r->inflight;c.sequence=sequence;memcpy(c.sample_words,r->sample_words,32);
  if(!bp_command_encode(&c,r->command_wire))return false;
 }
 r->samples_dirty=false;r->pending_custody=0;r->progress_timer=false;
 memcpy(wire,r->command_wire,BP_COMMAND_BYTES);return true;
}
bool bpr_command(BpReceiver *r,uint8_t wire[BP_COMMAND_BYTES]){
 return bpr_command_at(r,wire,0,true);
}
