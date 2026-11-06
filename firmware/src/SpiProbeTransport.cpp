#include "SpiProbeTransport.h"
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
#include "SharedSpiBus.h"
#include "../can-fd/common/protocol/bodaqs_spi_probe.h"
#include "esp_timer.h"
#include <string.h>

namespace {
SpiProbeTransport::Stats s_stats;
const board::BoardProfile* s_board=nullptr;
uint32_t s_caseId=0,s_hz=0,s_lastTransferUs=0,s_progressUs=0;
uint32_t s_noProgressSlots=0;
uint16_t s_bytes=0;
uint8_t s_profile=255,s_node=0,s_nodes=0,s_lockFailures=0;
bool s_open=false,s_entered=false,s_healthy=false,s_haveTransfer=false;
bool s_beforeEngine=false,s_beforeAdapter=false;
struct Node {
  uint8_t bytes[1008]={};
  uint32_t object=1,crc=0,mask=0;
  bool accepted=false;
} s_nodeState[4];
uint8_t s_tx[256],s_rx[256];
uint32_t us_() {return static_cast<uint32_t>(esp_timer_get_time());}
BodaqsSpiProbeFrame request_(uint8_t opcode) {
  BodaqsSpiProbeFrame f{};f.opcode=opcode;f.case_id=s_caseId;f.profile=s_profile;return f;
}
bool exchange_(const BodaqsSpiProbeFrame& q,BodaqsSpiProbeFrame& reply,bool timed) {
  uint32_t t0=us_();
  if(!bodaqs_spi_probe_encode(&q,s_tx,s_bytes))return false;
  if(timed)TimingStats_record(s_stats.encode,us_()-t0);
  t0=us_();
  // Same production mutex as ADS1220. The endpoint guard never owns that mutex.
  while(s_haveTransfer && static_cast<uint32_t>(us_()-s_lastTransferUs)<25) {
    const uint32_t gap=static_cast<uint32_t>(us_()-s_lastTransferUs);
    if(gap<25)delayMicroseconds(25-gap);
  }
  if(timed)TimingStats_record(s_stats.guard,us_()-t0);
  t0=us_();
  const bool ok=SharedSpiBus::transfer(s_board->can_fd_master.cs_pin,
      SPISettings(s_hz,MSBFIRST,SPI_MODE0),s_tx,s_rx,s_bytes);
  s_lastTransferUs=us_();s_haveTransfer=true;
  if(timed) {++s_stats.slots;TimingStats_record(s_stats.slot,s_lastTransferUs-t0);}
  if(!ok) {if(timed) {++s_stats.transferErrors;if(++s_lockFailures>=8)s_healthy=false;}return false;}
  s_lockFailures=0;
  t0=us_();const bool valid=bodaqs_spi_probe_decode(s_rx,s_bytes,&reply);
  if(timed)TimingStats_record(s_stats.decode,us_()-t0);
  if(!valid) {if(timed)++s_stats.wireErrors;return false;}
  if(reply.case_id!=s_caseId || reply.profile!=s_profile) {if(timed)++s_stats.stale;return false;}
  return true;
}
bool control_(const BodaqsSpiProbeFrame& q,BodaqsSpiProbeFrame* result=nullptr) {
  const uint32_t began=us_();
  for(unsigned attempt=0;attempt<4096 && static_cast<uint32_t>(us_()-began)<500000;++attempt) {
    BodaqsSpiProbeFrame reply{};
    if(!exchange_(q,reply,false))continue;
    if(reply.opcode!=(q.opcode|BODAQS_PROBE_RESPONSE) || reply.node!=q.node ||
        reply.fragment!=q.fragment || reply.object_id!=q.object_id || reply.logical_crc!=q.logical_crc)continue;
    const bool valid=q.opcode==BODAQS_PROBE_STATS?reply.payload_length==40:
        reply.payload_length==1 && reply.payload[0]==BODAQS_PROBE_OK;
    if(valid) {if(result)*result=reply;return true;}
  }
  return false;
}
bool masterStats_(uint8_t page,uint32_t* out) {
  auto q=request_(BODAQS_PROBE_STATS);q.fragment=page;
  BodaqsSpiProbeFrame result{};if(!control_(q,&result))return false;
  for(uint8_t i=0;i<10;++i) {
    const uint8_t* p=&result.payload[i*4];
    out[i]=static_cast<uint32_t>(p[0])|(static_cast<uint32_t>(p[1])<<8)|
        (static_cast<uint32_t>(p[2])<<16)|(static_cast<uint32_t>(p[3])<<24);
  }
  return true;
}
void failAccept_() {++s_stats.acceptErrors;s_healthy=false;}
void consume_(const BodaqsSpiProbeFrame& r) {
  if(r.opcode==(BODAQS_PROBE_ERROR|BODAQS_PROBE_RESPONSE)) {failAccept_();return;}
  if(r.node>=s_nodes) {failAccept_();return;}
  auto& n=s_nodeState[r.node];
  if(r.object_id!=n.object) {++s_stats.stale;return;}
  if(r.opcode==(BODAQS_PROBE_ACK|BODAQS_PROBE_RESPONSE)) {
    if(!n.accepted || r.logical_crc!=n.crc || r.fragment || r.payload_length!=1 || r.payload[0]) {failAccept_();return;}
    ++s_stats.validResponses;
    ++s_stats.retiredObjects;
    if(n.object==UINT32_MAX) {s_healthy=false;return;}
    ++n.object;n.mask=0;n.accepted=false;n.crc=0;
    s_node=(r.node+1)%s_nodes;s_progressUs=us_();s_noProgressSlots=0;return;
  }
  if(r.opcode!=(BODAQS_PROBE_POLL|BODAQS_PROBE_RESPONSE)) {++s_stats.stale;return;}
  const uint8_t fragments=bodaqs_spi_probe_fragment_count(s_profile);
  const uint16_t capacity=s_bytes-24;
  const uint16_t offset=r.fragment*capacity;
  const uint16_t remaining=offset<1008?1008-offset:0;
  const uint8_t expectedLength=remaining<capacity?remaining:capacity;
  if(r.fragment>=fragments || !expectedLength || r.payload_length!=expectedLength ||
      r.logical_crc!=bodaqs_spi_probe_known_crc(s_caseId,r.node,n.object)) {failAccept_();return;}
  for(uint8_t i=0;i<r.payload_length;++i) {
    if(r.payload[i]!=bodaqs_spi_probe_known_byte(s_caseId,r.node,n.object,offset+i)) {failAccept_();return;}
  }
  ++s_stats.validResponses;
  const uint32_t bit=1UL<<r.fragment;
  if(n.mask&bit) {++s_stats.duplicates;return;}
  memcpy(n.bytes+offset,r.payload,r.payload_length);n.mask|=bit;n.crc=r.logical_crc;
  s_progressUs=us_();s_noProgressSlots=0;
  if(n.mask==((1UL<<fragments)-1)) {
    if(bodaqs_spi_probe_crc(n.bytes,1008)!=n.crc) {failAccept_();return;}
    // RAM acceptance is counted once, before any ACK can retire this object.
    n.accepted=true;++s_stats.uniqueObjects;s_stats.acceptedBytes+=1008;
  }
}
}
namespace SpiProbeTransport {
bool begin(const board::BoardProfile& board,uint32_t caseId,uint16_t bytes,uint32_t hz,uint8_t nodes) {
  if(s_open || !board.can_fd_master.supported || board.can_fd_master.cs_pin<0)return false;
  const uint8_t profile=bodaqs_spi_probe_profile(bytes,hz,nodes);
  if(profile==255 || !caseId)return false;
  s_board=&board;s_caseId=caseId;s_bytes=bytes;s_hz=hz;s_nodes=nodes;s_node=0;s_profile=profile;
  s_stats=Stats{};for(auto& n:s_nodeState)n=Node{};
  s_lockFailures=0;s_noProgressSlots=0;s_open=true;s_entered=false;s_healthy=false;
  if(!control_(request_(BODAQS_PROBE_BEGIN)))return false;
  s_entered=true;
  s_beforeEngine=masterStats_(0,s_stats.masterBefore);
  s_beforeAdapter=masterStats_(1,s_stats.adapterBefore);
  s_progressUs=us_();s_healthy=true;return true;
}
void tick() {
  if(!s_open || !s_entered || !s_healthy)return;
  if(++s_noProgressSlots>4096 || static_cast<uint32_t>(us_()-s_progressUs)>500000) {s_healthy=false;return;}
  const auto& n=s_nodeState[s_node];
  auto q=request_(n.accepted?BODAQS_PROBE_ACK:BODAQS_PROBE_POLL);
  q.node=s_node;q.object_id=n.object;
  if(n.accepted)q.logical_crc=n.crc;
  else {while(n.mask&(1UL<<q.fragment))++q.fragment;}
  BodaqsSpiProbeFrame r{};
  if(exchange_(q,r,true))consume_(r);
}
bool healthy() {return s_healthy;}
bool stop() {
  if(!s_open)return true;
  if(s_entered) {
    const bool afterEngine=masterStats_(0,s_stats.masterAfter);
    const bool afterAdapter=masterStats_(1,s_stats.adapterAfter);
    s_stats.masterMeasured=s_beforeEngine && afterEngine;
    s_stats.adapterMeasured=s_beforeAdapter && afterAdapter;
  }
  if(!control_(request_(BODAQS_PROBE_STOP)))return false;
  s_open=false;s_entered=false;s_healthy=false;return true;
}
const Stats& stats() {return s_stats;}
}
#endif
