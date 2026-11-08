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
bool s_beforeEngine=false,s_beforeAdapter=false,s_beforeDiagnostic=false;
bool s_beforeProcessing=false;
bool s_beforeReceive=false;
SpiProbeTransport::CrcMode s_crcMode=SpiProbeTransport::CrcMode::Legacy;
uint32_t s_interval=0,s_lastStartUs=0,s_lastRequestUs=0;
bool s_haveRequest=false;
bool s_haveStart=false,s_switch=false,s_switchDue=false;
uint32_t us_();
BodaqsSpiProbeFrame request_(uint8_t opcode);
uint32_t expectedCrc_(uint8_t node,uint32_t object) {
  const uint32_t began=us_();
  const uint32_t crc=bodaqs_spi_probe_known_crc(s_caseId,node,object);
  TimingStats_record(s_stats.expectedCrc,us_()-began);return crc;
}
struct Node {
  uint8_t bytes[1008]={};
  uint32_t object=1,crc=0,mask=0;
  bool accepted=false,expectedValid=false;
  uint32_t expected=0;
} s_nodeState[4];
// One immutable selected object per node, at most four distinct requests total.
// A request clocks an older reply; it does not synchronously return its own.
constexpr uint32_t kRetryUs=5000;
struct Pending {
  bool used=false;
  uint8_t node=0,fragment=0,retries=0;
  bool ack=false;
  uint32_t object=0,firstUs=0,retryUs=0;
} s_pending[4];
uint8_t s_pipeCursor=0;
void completed_(const BodaqsSpiProbeFrame& r) {
  if(!s_stats.pipelined)return;
  for(auto& p:s_pending)if(p.used && p.node==r.node && p.object==r.object_id &&
      p.fragment==r.fragment && p.ack==(r.opcode==(BODAQS_PROBE_ACK|BODAQS_PROBE_RESPONSE))) {
    TimingStats_record(s_stats.replyAge,us_()-p.firstUs);
    p.used=false;--s_stats.pendingRequests;return;
  }
}
bool pipelineRequest_(BodaqsSpiProbeFrame& q) {
  const uint32_t now=us_();
  Pending *oldest=nullptr,*free=nullptr;
  for(auto& p:s_pending) {
    if(!p.used){if(!free)free=&p;continue;}
    if(!oldest || static_cast<uint32_t>(now-p.retryUs)>static_cast<uint32_t>(now-oldest->retryUs))oldest=&p;
  }
  Pending* selected=nullptr;
  if(oldest && static_cast<uint32_t>(now-oldest->retryUs)>=kRetryUs) {
    if(oldest->retries==8){++s_stats.retryExhausted;s_healthy=false;return false;}
    selected=oldest;++selected->retries;selected->retryUs=now;++s_stats.retryRequests;
  } else if(free) {
    for(uint8_t offset=0;offset<s_nodes;++offset) {
      const uint8_t node=(s_pipeCursor+offset)%s_nodes;
      const auto& n=s_nodeState[node];
      uint32_t requested=n.mask;bool ackPending=false;
      for(const auto& p:s_pending)if(p.used && p.node==node) {
        if(p.ack)ackPending=true;else requested|=1UL<<p.fragment;
      }
      uint8_t fragment=0;
      if(n.accepted) {if(ackPending)continue;}
      else {
        const uint8_t fragments=bodaqs_spi_probe_fragment_count(s_profile);
        while(fragment<fragments && (requested&(1UL<<fragment)))++fragment;
        if(fragment==fragments)continue;
      }
      *free=Pending{};free->used=true;free->node=node;free->object=n.object;
      free->ack=n.accepted;free->fragment=fragment;free->firstUs=free->retryUs=now;
      selected=free;s_pipeCursor=(node+1)%s_nodes;
      ++s_stats.newRequests;++s_stats.pendingRequests;
      if(s_stats.pendingRequests>s_stats.pendingHighWater)s_stats.pendingHighWater=s_stats.pendingRequests;
      break;
    }
  }
  if(!selected) {
    // No NOP exists in wire v1. Repeat one pending request to retrieve the
    // reply, without extending its retry deadline or allocating another entry.
    selected=oldest;if(!selected)return false;++s_stats.clockRequests;
  }
  q=request_(selected->ack?BODAQS_PROBE_ACK:BODAQS_PROBE_POLL);
  q.node=selected->node;q.object_id=selected->object;q.fragment=selected->fragment;
  if(selected->ack)q.logical_crc=s_nodeState[selected->node].crc;
  return true;
}
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
  while((s_haveTransfer && static_cast<uint32_t>(us_()-s_lastTransferUs)<25) ||
      (s_haveRequest && static_cast<uint32_t>(us_()-s_lastRequestUs)<s_interval)) {
    const uint32_t gap=static_cast<uint32_t>(us_()-s_lastTransferUs);
    const uint32_t requestGap=static_cast<uint32_t>(us_()-s_lastRequestUs);
    const uint32_t csWait=s_haveTransfer && gap<25?25-gap:0;
    const uint32_t paceWait=s_haveRequest && requestGap<s_interval?s_interval-requestGap:0;
    delayMicroseconds(csWait>paceWait?csWait:paceWait);
  }
  if(timed)TimingStats_record(s_stats.guard,us_()-t0);
  t0=us_();
  SharedSpiBus::ProbeContext context;
  const bool ok=SharedSpiBus::transfer(s_board->can_fd_master.cs_pin,
      SPISettings(s_hz,MSBFIRST,SPI_MODE0),s_tx,s_rx,s_bytes,50,nullptr,nullptr,&context);
  s_lastTransferUs=us_();
  if(ok) {
    s_haveTransfer=true;s_lastRequestUs=context.csAssertUs;s_haveRequest=true;
    if(timed) {
      if(s_haveStart)TimingStats_record(s_stats.requestInterval,static_cast<uint32_t>(context.csAssertUs-s_lastStartUs));
      s_lastStartUs=context.csAssertUs;s_haveStart=true;
    }
  }
  if(timed) {++s_stats.slots;TimingStats_record(s_stats.slot,s_lastTransferUs-t0);}
  if(!ok) {if(timed) {++s_stats.transferErrors;if(++s_lockFailures>=8)s_healthy=false;}return false;}
  s_lockFailures=0;
  t0=us_();const auto reason=bodaqs_spi_probe_decode_result(s_rx,s_bytes,&reply);
  const bool valid=reason==BODAQS_SPI_PROBE_DECODE_OK;
  if(timed)TimingStats_record(s_stats.decode,us_()-t0);
  if(timed) {
    ++s_stats.decodeCounts[reason];
    const int8_t previous=context.previousValid?context.previousCs:-1;
    for(auto& p:s_stats.byPreviousCs)if(!p.used || p.cs==previous) {
      p.used=true;p.cs=previous;if(valid)++p.responses;else ++p.decodeFailures;break;
    }
    const auto& operation=context.previousOperation;
    bool bucketed=false;
    for(auto& p:s_stats.byPreviousOperation) {
      const auto& o=p.operation;
      if(p.used && (p.cs!=previous || o.bytes!=operation.bytes || o.tx0!=operation.tx0 ||
          o.hasTx!=operation.hasTx || o.hasRx!=operation.hasRx))continue;
      p.used=true;p.cs=previous;p.operation=operation;
      if(valid)++p.responses;else ++p.decodeFailures;
      bucketed=true;break;
    }
    if(!bucketed)++s_stats.operationBucketsOmitted;
    if(!valid) {
      if(s_stats.failureCount<4) {
        auto& f=s_stats.failures[s_stats.failureCount++];
        f.reason=reason;f.slot=s_stats.slots;f.frameBytes=s_bytes;f.bus=context;
        f.opcode=q.opcode;f.node=q.node;f.fragment=q.fragment;f.profile=q.profile;
        f.caseId=q.case_id;f.objectId=q.object_id;f.logicalCrc=q.logical_crc;
        memcpy(f.rx,s_rx,s_bytes);
      } else ++s_stats.failureSamplesOmitted;
    }
  }
  if(!valid) {if(timed)++s_stats.wireErrors;return false;}
  if(reply.case_id!=s_caseId || reply.profile!=s_profile) {if(timed)++s_stats.stale;return false;}
  return true;
}
bool control_(const BodaqsSpiProbeFrame& q,BodaqsSpiProbeFrame* result=nullptr) {
  const uint32_t began=us_();
  for(unsigned attempt=0;attempt<4096 && static_cast<uint32_t>(us_()-began)<500000;++attempt) {
    BodaqsSpiProbeFrame reply{};
    if(!exchange_(q,reply,false))continue;
    if(q.opcode==BODAQS_PROBE_STATS && reply.opcode==(BODAQS_PROBE_ERROR|BODAQS_PROBE_RESPONSE) &&
        reply.node==q.node && reply.fragment==q.fragment && reply.object_id==q.object_id && reply.logical_crc==q.logical_crc)return false;
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
    completed_(r);
    ++s_stats.validResponses;
    ++s_stats.retiredObjects;
    if(n.object==UINT32_MAX) {s_healthy=false;return;}
    ++n.object;n.mask=0;n.accepted=false;n.crc=0;n.expectedValid=false;
    s_node=(r.node+1)%s_nodes;s_progressUs=us_();s_noProgressSlots=0;return;
  }
  if(r.opcode!=(BODAQS_PROBE_POLL|BODAQS_PROBE_RESPONSE)) {++s_stats.stale;return;}
  const uint8_t fragments=bodaqs_spi_probe_fragment_count(s_profile);
  const uint16_t capacity=s_bytes-24;
  const uint16_t offset=r.fragment*capacity;
  const uint16_t remaining=offset<1008?1008-offset:0;
  const uint8_t expectedLength=remaining<capacity?remaining:capacity;
  const uint32_t expected=s_crcMode==SpiProbeTransport::CrcMode::Cached?
      (n.expectedValid?n.expected:(n.expected=expectedCrc_(r.node,n.object),n.expectedValid=true,n.expected)):
      expectedCrc_(r.node,n.object);
  if(r.fragment>=fragments || !expectedLength || r.payload_length!=expectedLength ||
      r.logical_crc!=expected) {failAccept_();return;}
  for(uint8_t i=0;i<r.payload_length;++i) {
    if(r.payload[i]!=bodaqs_spi_probe_known_byte(s_caseId,r.node,n.object,offset+i)) {failAccept_();return;}
  }
  ++s_stats.validResponses;
  completed_(r);
  const uint32_t bit=1UL<<r.fragment;
  if(n.mask&bit) {++s_stats.duplicates;return;}
  memcpy(n.bytes+offset,r.payload,r.payload_length);n.mask|=bit;n.crc=r.logical_crc;
  s_progressUs=us_();s_noProgressSlots=0;
  if(n.mask==((1UL<<fragments)-1)) {
    const uint32_t began=us_();
    const uint32_t crc=bodaqs_spi_probe_crc(n.bytes,1008);
    TimingStats_record(s_stats.objectCrc,us_()-began);
    if(crc!=n.crc) {failAccept_();return;}
    // RAM acceptance is counted once, before any ACK can retire this object.
    n.accepted=true;++s_stats.uniqueObjects;s_stats.acceptedBytes+=1008;
  }
}
}
namespace SpiProbeTransport {
bool requestDue() {
  return s_open && s_entered && s_healthy && !s_switchDue &&
      (!s_haveTransfer || static_cast<uint32_t>(us_()-s_lastTransferUs)>=25) &&
      (!s_haveRequest || static_cast<uint32_t>(us_()-s_lastRequestUs)>=s_interval);
}
bool begin(const board::BoardProfile& board,uint32_t caseId,uint16_t bytes,uint32_t hz,uint8_t nodes,CrcMode crcMode,uint32_t startIntervalUs,bool switchMode,bool pipelined) {
  if(s_open || !board.can_fd_master.supported || board.can_fd_master.cs_pin<0)return false;
  const uint8_t profile=bodaqs_spi_probe_profile(bytes,hz,nodes);
  if(profile==255 || !caseId || startIntervalUs>5000 || (pipelined && switchMode))return false;
  s_board=&board;s_caseId=caseId;s_bytes=bytes;s_hz=hz;s_nodes=nodes;s_node=0;s_profile=profile;
  s_stats=Stats{};for(auto& n:s_nodeState)n=Node{};
  s_stats.pipelined=pipelined;s_pipeCursor=0;for(auto& p:s_pending)p=Pending{};
  s_crcMode=crcMode;s_interval=startIntervalUs;s_switch=switchMode;s_switchDue=false;
  s_haveStart=false;s_haveRequest=false; // Preserve the inter-CS guard across cases.
  s_lockFailures=0;s_noProgressSlots=0;s_open=true;s_entered=false;s_healthy=false;
  if(!control_(request_(BODAQS_PROBE_BEGIN)))return false;
  s_entered=true;
  s_beforeAdapter=masterStats_(1,s_stats.adapterBefore);
  s_beforeDiagnostic=masterStats_(2,s_stats.diagnosticBefore);
  const bool processing=masterStats_(3,s_stats.processingBefore);
  const bool metadata=masterStats_(4,s_stats.processingMetaBefore);
  s_beforeProcessing=processing && metadata;
  const bool receive=masterStats_(5,s_stats.receiveBefore);
  const bool turnover=masterStats_(6,s_stats.turnoverBefore);
  s_beforeReceive=receive && turnover;
  // Finish on the original universally supported page. Older peers reject
  // optional pages; ordered delayed ERROR replies must leave before data starts.
  s_beforeEngine=masterStats_(0,s_stats.masterBefore);
  s_progressUs=us_();s_healthy=true;return true;
}
void tick() {
  if(!s_open || !s_entered || !s_healthy)return;
  // Defer without acquiring the bus or sleeping; caller continues row/STOP work.
  if(s_haveTransfer && static_cast<uint32_t>(us_()-s_lastTransferUs)<25) {++s_stats.pacingDeferred;++s_stats.csGuardDeferred;return;}
  if(s_haveRequest && static_cast<uint32_t>(us_()-s_lastRequestUs)<s_interval) {++s_stats.pacingDeferred;++s_stats.intervalDeferred;return;}
  const uint32_t began=us_();
  if(s_switchDue) {
    if(SharedSpiBus::probeUnselectedClocks(s_board->spi))++s_stats.switchTransfers;
    else {++s_stats.switchFailures;s_healthy=false;}
    s_switchDue=false;TimingStats_record(s_stats.iteration,us_()-began);return;
  }
  if(++s_noProgressSlots>4096 || static_cast<uint32_t>(us_()-s_progressUs)>500000) {s_healthy=false;return;}
  BodaqsSpiProbeFrame q{};
  if(s_stats.pipelined) {if(!pipelineRequest_(q))return;}
  else {
    const auto& n=s_nodeState[s_node];
    q=request_(n.accepted?BODAQS_PROBE_ACK:BODAQS_PROBE_POLL);
    q.node=s_node;q.object_id=n.object;
    if(n.accepted)q.logical_crc=n.crc;
    else {while(n.mask&(1UL<<q.fragment))++q.fragment;}
  }
  BodaqsSpiProbeFrame r{};
  if(exchange_(q,r,true)) {
    const uint32_t validating=us_();consume_(r);
    TimingStats_record(s_stats.validate,us_()-validating);
  }
  TimingStats_record(s_stats.iteration,us_()-began);
  s_switchDue=s_switch;
}
bool healthy() {return s_healthy;}
bool stop() {
  if(!s_open)return true;
  if(s_entered) {
    const bool afterEngine=masterStats_(0,s_stats.masterAfter);
    const bool afterAdapter=masterStats_(1,s_stats.adapterAfter);
    const bool afterDiagnostic=masterStats_(2,s_stats.diagnosticAfter);
    const bool processing=masterStats_(3,s_stats.processingAfter);
    const bool metadata=masterStats_(4,s_stats.processingMetaAfter);
    s_stats.processingMeasured=s_beforeProcessing && processing && metadata;
    const bool receive=masterStats_(5,s_stats.receiveAfter);
    const bool turnover=masterStats_(6,s_stats.turnoverAfter);
    s_stats.receiveMeasured=s_beforeReceive && receive && turnover;
    s_stats.diagnosticMeasured=s_beforeDiagnostic && afterDiagnostic;
    s_stats.masterMeasured=s_beforeEngine && afterEngine;
    s_stats.adapterMeasured=s_beforeAdapter && afterAdapter;
  }
  if(!control_(request_(BODAQS_PROBE_STOP)))return false;
  s_open=false;s_entered=false;s_healthy=false;return true;
}
const Stats& stats() {return s_stats;}
}
#endif
