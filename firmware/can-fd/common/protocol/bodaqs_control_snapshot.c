#include "bodaqs_control_snapshot.h"
#include <string.h>
static uint16_t u16(const uint8_t *p) { return (uint16_t)(p[0] | ((uint16_t)p[1]<<8)); }
static bool zero(const uint8_t *p, unsigned n) { while(n--) if(*p++) return false; return true; }
static bool group_zero(const uint8_t *d, unsigned bit) {
 static const uint8_t starts[12]={24,44,48,64,72,88,5,92,120,136,152,176};
 static const uint8_t sizes[12]={20,3,16,8,16,4,1,16,16,8,24,5};
 if(!zero(d+starts[bit],sizes[bit])) return false;
 if(bit==0 && !zero(d+144,8)) return false;
 if(bit==5 && d[47]) return false;
 if(bit==7 && !zero(d+112,8)) return false;
 if(bit==10 && !zero(d+108,4)) return false;
 return true;
}
bool bodaqs_control_descriptor_valid(const uint8_t *d,size_t len,uint16_t schema,uint8_t endpoint) {
 unsigned i; uint32_t applicable,known,historical;
 if(!d || u16(d)!=schema || u16(d+2)!=1) return false;
 if(schema==2) {
  if(len!=128 || d[4]!=endpoint || d[5]>1 || d[6]>16 || d[7] ||
   (bodaqs_control_get_u32(d+8)&~31U) || (bodaqs_control_get_u32(d+12)&~15U) ||
   (bodaqs_control_get_u32(d+16)&~63U) || u16(d+20)!=1 || u16(d+22)!=1 ||
   u16(d+24)!=3 || u16(d+26)!=1 || u16(d+28)!=512 || d[30]!=24 || d[31] ||
   (u16(d+32)&~63U) || !(u16(d+32)&(1U<<endpoint)) || !zero(d+34,2) || !zero(d+48,16)) return false;
  for(i=0;i<16;i++) {
   if(i<d[6]) { if(!u16(d+64+4*i) || !u16(d+66+4*i)) return false; }
   else if(!zero(d+64+4*i,4)) return false;
  }
  return true;
 }
 if(schema!=3 || len!=192 || d[4]>3 || (d[5]&~3U) || d[6]>1 || d[7]>1 ||
   (bodaqs_control_get_u32(d+20)&~63U) || !zero(d+94,2) || !zero(d+174,2) || !zero(d+181,3) || !bodaqs_control_get_u64(d+184)) return false;
 applicable=bodaqs_control_get_u32(d+8);known=bodaqs_control_get_u32(d+12);historical=bodaqs_control_get_u32(d+16);
 if((applicable&~BODAQS_CONTROL_FIELD_GROUPS) || (known&~applicable) || (historical&~known)) return false;
 for(i=0;i<12;i++) if(!(known&(1U<<i)) && !group_zero(d,i)) return false;
 if((known&(1U<<2)) && (!bodaqs_control_get_u32(d+52)||!bodaqs_control_get_u32(d+60))) return false;
 if((known&(1U<<4)) && (!bodaqs_control_get_u32(d+76)||!bodaqs_control_get_u32(d+84))) return false;
 if((known&(1U<<7)) && !bodaqs_control_get_u32(d+104)) return false;
 if((known&(1U<<8)) && (!bodaqs_control_get_u32(d+124)||!bodaqs_control_get_u32(d+132))) return false;
 if((known&(1U<<1)) && (u16(d+44)!=1 || d[46]!=1)) return false;
 if((known&(1U<<5)) && (d[47]!=1 || (bodaqs_control_get_u32(d+88)&~15U))) return false;
 return true;
}
void bodaqs_control_unconfigured_descriptor(const BodaqsControlNode *n,uint8_t ep,bool effective,uint8_t *d) {
 memset(d,0,effective?192:128);d[0]=effective?3:2;d[2]=1;
 if(effective) {
  bodaqs_control_put_u32(d+8,BODAQS_CONTROL_FIELD_GROUPS);
  bodaqs_control_put_u32(d+20,32U | ((n->flags&(1U<<7))?8U:0U));
  bodaqs_control_put_u64(d+184,n->endpoint_epoch[ep]);
 } else {
  d[4]=ep;d[5]=ep==0?1:0;d[16]=32;d[20]=1;d[22]=1;d[24]=3;d[26]=1;d[29]=2;d[30]=24;
  d[32]=(uint8_t)n->endpoint_mask;d[33]=(uint8_t)(n->endpoint_mask>>8);
 }
}
static void error(BodaqsControlRecord *r,uint8_t reason) {
 uint8_t opcode=r->opcode; r->opcode=BODAQS_CONTROL_ERROR;r->data_length=24;
 memset(r->data,0,24);r->data[0]=1;r->data[1]=reason;r->data[3]=opcode;
}
bool bodaqs_control_snapshot_process(BodaqsControlSnapshot *s,const BodaqsControlNode *n,const BodaqsControlRecord *q,uint32_t now,BodaqsControlRecord *r) {
 bool opening=q->opcode==5 || q->opcode==6;
 if(!opening && q->opcode!=7 && q->opcode!=8) return false;
 if(!bodaqs_control_request_valid(q)) return false;
 *r=*q;memset(r->data,0,24);r->data_length=24;
 if(q->node_boot_id!=n->boot_id) {error(r,4);return true;}
 if(q->session && q->session!=n->active_session) {error(r,5);return true;}
 if(!(n->endpoint_mask&(1U<<q->endpoint))) {error(r,23);return true;}
 if(s->pinned && (uint32_t)(now-s->opened_ms)>=5000U) {s->pinned=false;s->expired=true;}
 if(opening) {
  bool same=s->id && s->opening.operation==q->operation && s->opening.session==q->session && s->opening.endpoint==q->endpoint && s->opening.opcode==q->opcode;
  if(same && s->expired) {error(r,10);return true;}
  if(!same && s->pinned) {error(r,7);return true;}
  if(!same) {
   if(s->next_id==UINT64_MAX) {error(r,22);return true;}
   s->id=++s->next_id;s->opening=*q;s->opened_ms=now;s->pinned=true;s->expired=false;
   s->length=q->opcode==5?128:192;
   if(s->capture) s->capture(s->capture_context,n,q->endpoint,q->opcode==6,s->bytes);
   else bodaqs_control_unconfigured_descriptor(n,q->endpoint,q->opcode==6,s->bytes);
   if(!bodaqs_control_descriptor_valid(s->bytes,s->length,q->opcode==5?2:3,q->endpoint)) {s->pinned=false;s->expired=true;error(r,1);return true;}
  }
  r->transfer=s->id;r->data[0]=q->opcode==5?2:3;r->data[2]=1;
  r->data[4]=(uint8_t)s->length;r->data[5]=(uint8_t)(s->length>>8);r->data[6]=(uint8_t)((s->length+23)/24);
  if(q->opcode==6) {memcpy(r->data+8,s->bytes+32,8);memcpy(r->data+16,s->bytes+184,8);}
  return true;
 }
 if(!s->pinned || q->transfer!=s->id || q->operation!=s->opening.operation || q->session!=s->opening.session || q->endpoint!=s->opening.endpoint) {error(r,10);return true;}
 if(q->opcode==8) {s->pinned=false;s->expired=true;return true;}
 if(q->page>=(s->length+23)/24) {error(r,9);return true;}
 r->data_length=(uint8_t)(s->length-q->page*24);if(r->data_length>24) r->data_length=24;
 memcpy(r->data,s->bytes+q->page*24,r->data_length);return true;
}
