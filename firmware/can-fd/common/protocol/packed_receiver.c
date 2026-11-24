#include "packed_receiver.h"
#if BODAQS_PACKED_PROGRESS
#include "packed_progress_receiver.inc"
#else
#include "packed_receiver.h"
static unsigned cell_index(unsigned cls,unsigned node,uint32_t object) {
 return cls==1?4*node+(object-1)%4:cls==5?28:16+4*(cls-2)+node;
}
bool bpr_init(BpReceiver *r,uint64_t context,bool selected) {
 if(!r || !context || !selected)return false;
#if defined(BODAQS_PACKED_SEGMENTED_RECEIVER) && BODAQS_PACKED_SEGMENTED_RECEIVER
 uint8_t *storage[29];
 for(unsigned i=0;i<29;++i){storage[i]=r->cells[i].bytes;if(!storage[i])return false;}
#endif
 memset(r,0,sizeof(*r));
#if defined(BODAQS_PACKED_SEGMENTED_RECEIVER) && BODAQS_PACKED_SEGMENTED_RECEIVER
 for(unsigned i=0;i<29;++i){r->cells[i].bytes=storage[i];memset(storage[i],0,468);}
#endif
 r->context=context;for(unsigned n=0;n<4;++n)r->base[n]=r->next[n]=1;return true;
}
void bpr_pump(BpReceiver *r,BpAdmit admit,void *arg) {
 if(!r || !admit)return;
 for(unsigned i=0;i<29;++i){BpReceiverCell *c=&r->cells[i];
  if(c->state.complete && !c->admitted && !c->retired &&
   (c->state.cls!=1 || c->state.object==r->next[c->state.node]) &&
   admit(arg,bodaqs_fragment_kind(c->state.cls),c->state.node,c->state.object,c->bytes,c->state.total)) {
   c->admitted=true;if(c->state.cls==1)++r->next[c->state.node];
  }}
}
static void confirm(BpReceiver *r,uint32_t sequence) {
 if(!r->awaiting || sequence!=r->inflight.sequence)return;
 for(unsigned i=0;i<r->inflight.count;++i){const BpAck *a=&r->inflight.acks[i];
  BpReceiverCell *c=&r->cells[cell_index(a->cls,a->node,a->object)];
  /* Cells remain pinned from command construction through confirmation. */
  if(c->state.object!=a->object || c->state.checksum!=a->checksum || !c->admitted){r->exhausted=true;return;}
 }
 for(unsigned i=0;i<r->inflight.count;++i){const BpAck *a=&r->inflight.acks[i];
  BpReceiverCell *c=&r->cells[cell_index(a->cls,a->node,a->object)];c->retired=true;c->confirmed=a->object;
  if(a->cls!=1){c->state.object=0;c->state.complete=false;c->admitted=false;}
 }
 for(unsigned n=0;n<4;++n)while(r->base[n]<=UINT32_MAX-4){
  BpReceiverCell *c=&r->cells[cell_index(1,n,r->base[n])];
  if(!c->retired || c->state.object!=r->base[n])break;
  c->state.object=0;c->state.complete=false;c->admitted=c->retired=false;++r->base[n];
 }
 r->awaiting=false;
}
bool bpr_receive(BpReceiver *r,const uint8_t wire[512],BpAdmit admit,void *arg) {
 if(!r || r->exhausted)return false;
 BpReply reply;if(!bp_decode(wire,512,r->context,&reply) || reply.confirmed_command>r->sequence)return false;
 return bpr_receive_decoded(r,&reply,admit,arg);
}
bool bpr_receive_decoded(BpReceiver *r,const BpReply *decoded,BpAdmit admit,void *arg) {
 return bpr_receive_decoded_notify(r,decoded,admit,arg,NULL,NULL);
}
bool bpr_receive_decoded_notify(BpReceiver *r,const BpReply *decoded,BpAdmit admit,void *arg,BpConfirmed notified,void *notification_arg) {
 if(!r || r->exhausted || !decoded || decoded->context!=r->context || decoded->confirmed_command>r->sequence)return false;
 const BpReply reply=*decoded;
 const bool confirming=r->awaiting && reply.confirmed_command==r->inflight.sequence;
 confirm(r,reply.confirmed_command);if(r->exhausted)return false;
 if(confirming && notified)for(unsigned i=0;i<r->inflight.count;++i)
  notified(notification_arg,&r->inflight.acks[i]);
 for(unsigned i=0;i<reply.count;++i){const BpItem *item=&reply.items[i];const unsigned cls=bodaqs_fragment_class(item->kind);
  if(cls==1 && item->object<r->base[item->node])continue; // confirmed late physical copy
  if(cls==1 && item->object-r->base[item->node]>=4){++r->rejected;continue;}
  BpReceiverCell *c=&r->cells[cell_index(cls,item->node,item->object)];
  if(cls!=1 && item->object<=c->confirmed)continue;
  if(c->state.object && c->state.object!=item->object){++r->rejected;continue;}
  if(!c->state.object)c->retired=false;
  /* bp_decode supplies a complete immutable object view for this synchronous
   * call. Shared validation still copies into owned retained storage; the
   * physical RX buffer is never admitted downstream or retained by reference. */
  const BodaqsFragmentView view={item->body,r->context,item->object,item->length,
      item->length,item->node,item->kind,0};
  if(bodaqs_fragment_accept_view(&c->state,c->bytes,468,&view,1,NULL)<1){++r->rejected;continue;}
 }
 bpr_pump(r,admit,arg);return true;
}
bool bpr_command(BpReceiver *r,uint8_t wire[BP_COMMAND_BYTES]) {
 if(!r || r->exhausted)return false;
 if(!wire)return false;
 if(r->awaiting){memcpy(wire,r->command_wire,BP_COMMAND_BYTES);return true;}
 if(r->sequence==UINT32_MAX){r->exhausted=true;return false;}
 BpCommand c={0};c.context=r->context;c.sequence=++r->sequence;
 /* One reserved protected-result opportunity; other slots rotate over every
  * retained cell, including metadata and all sample sources. Never rebuild an
  * awaiting vector: its exact identities remain pinned until confirmation. */
 unsigned protected_index=29;
 for(unsigned step=0;step<4;++step){unsigned n=(r->protected_cursor+step)%4;
  const BpReceiverCell *cell=&r->cells[24+n];
  if(cell->admitted && !cell->retired){
   c.acks[c.count++]=(BpAck){cell->state.object,cell->state.checksum,cell->state.total,cell->state.node,cell->state.cls,1};
   protected_index=24+n;r->protected_cursor=(uint8_t)((n+1)%4);break;}
 }
 const unsigned start=r->ack_cursor;
 for(unsigned step=0;step<29 && c.count<BP_MAX_ACKS;++step){unsigned i=(start+step)%29;
  const BpReceiverCell *cell=&r->cells[i];
  if(i!=protected_index && cell->admitted && !cell->retired){
   c.acks[c.count++]=(BpAck){cell->state.object,cell->state.checksum,cell->state.total,cell->state.node,cell->state.cls,1};
   r->ack_cursor=(uint8_t)((i+1)%29);}
 }
 /* Project only the contiguous retirement authorized by THIS exact batch.
  * No local cell is cleared here. The master validates/retires all ACKs before
  * using these grants; receive confirms that batch before accepting its items. */
 for(unsigned n=0;n<4;++n){
  uint32_t base=r->base[n];
  for(unsigned step=0;step<4 && base<=UINT32_MAX-4;++step){
   const BpReceiverCell *cell=&r->cells[cell_index(1,n,base)];
   bool retiring=cell->retired && cell->state.object==base;
   for(unsigned a=0;a<c.count;++a)if(c.acks[a].cls==1 && c.acks[a].node==n && c.acks[a].object==base)retiring=true;
   if(!retiring)break;
   ++base;
  }
  if(base>UINT32_MAX-4){r->exhausted=true;return false;}
  bodaqs_measurement_put(c.sample_words+8*n,base,4);
  for(unsigned i=0;i<4;++i){const BpReceiverCell *cell=&r->cells[cell_index(1,n,base+i)];
   if(cell->state.object==base+i && cell->state.complete)c.sample_words[8*n+4]|=1U<<i;
  }
 }
 if(!bp_command_encode(&c,r->command_wire))return false;
 r->inflight=c;r->awaiting=c.count!=0;memcpy(wire,r->command_wire,BP_COMMAND_BYTES);return true;
}

#endif
