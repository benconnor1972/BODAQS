#include "SpiMeasurementProbe.h"
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
#include "AnalogInputManager.h"
#include "SharedSpiBus.h"
#include "ConfigManager.h"
#include "PowerManager.h"
#include "SpiProbeTransport.h"
#include "SpiProbeRows.h"
#include "SpiProbeCodecConfig.h"
#include "esp_timer.h"
#include "freertos/task.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <limits.h>

#ifndef BODAQS_SPI_PROBE_BUILD
#error "Probe builds require source-derived BODAQS_SPI_PROBE_BUILD"
#endif

namespace {
const board::BoardProfile* s_board=nullptr;
LoggerConfig s_cfg;
struct Case {
  uint32_t id=0,hz=8000000,durationMs=1000;
  uint16_t frame=64;
  uint8_t nodes=1;
  bool adc=false,bulk=false,switchMode=false,cached=false,active=false,transportAttempted=false;
  bool sequence=false,selected=false,workerStartRequested=false;
  bool owner=false,workerControl=false,trafficStarted=false,ownerRows=false,pipelined=false,clockOnly=false;
  SpiProbeRowLedger rowLedger;
  uint32_t deadlineDeferrals=0;
  uint64_t lastOwnerReadUs[2]={};
  TimingSummary ownerReadGap[2];
  // Completed owner cycles only. Outcome buckets partition cycles; phase
  // summaries partition work within them. These are software observations.
  TimingSummary ownerCycle,adcReadyService,rowService,adcStartService,transportService;
  TimingSummary decision[6],dispatchHeadroom;
  uint8_t adcMask=3,adcCore=0,ownerCursor=0,ownerStep[2]={};
  uint32_t cycleUs=0;
  uint64_t ownerNextUs[2]={},ownerStartedUs[2]={};
  SharedSpiBus::ProbeTrafficWindow traffic;
  uint8_t sequenceAdc=0,sequenceStep=0;
  uint64_t sequenceStartedUs=0;
  uint32_t sequenceCounts[2][3]={},sequenceFailures=0,sequenceTimeouts=0;
  uint32_t startIntervalUs=0,retryUs=5000;
  uint64_t startUs=0,nextRowUs=0,elapsedUs=0;
  uint32_t rows=0,missedRows=0,commandErrors=0;
} s_case;
bool s_ready=false,s_blocked=false;
uint32_t s_lastCaseId=0;
char s_line[96];
uint8_t s_lineLength=0;
bool s_lineOverflow=false;

constexpr uint32_t kRowGuardUs=800;
uint64_t now_() { return static_cast<uint64_t>(esp_timer_get_time()); }
void error_(const char* reason) {
  Serial.printf("{\"schema\":\"bodaqs.spi-probe.v14\",\"type\":\"error\",\"reason\":\"%s\",\"logger_build\":\"%s\"}\n",reason,BODAQS_SPI_PROBE_BUILD);
}
void summary_(const TimingSummary& s) {
  Serial.printf("{\"count\":%lu,\"min_us\":%lu,\"max_us\":%lu,\"total_us\":%llu}",
      (unsigned long)s.count,(unsigned long)s.minUs,(unsigned long)s.maxUs,(unsigned long long)s.totalUs);
}
void array_(const uint32_t* values) {
  Serial.print('[');
  for(uint8_t i=0;i<10;++i) {if(i)Serial.print(',');Serial.printf("%lu",(unsigned long)values[i]);}
  Serial.print(']');
}
void operation_(const SharedSpiBus::ProbeOperation& o) {
  Serial.printf("{\"bytes\":%u,\"tx0\":%u,\"has_tx\":%s,\"has_rx\":%s}",
      o.bytes,o.tx0,o.hasTx?"true":"false",o.hasRx?"true":"false");
}
void finish_(const char* outcome,const char* reason);
void row_(const SpiProbeRow& r) {
  Serial.printf("{\"index\":%lu,\"scheduled_us\":%llu,\"published_us\":%llu,\"counts\":[%ld,%ld],\"conversion\":[%lu,%lu],\"acquired_us\":[%llu,%llu],\"valid_mask\":%u,\"fresh_mask\":%u}",
      (unsigned long)r.index,(unsigned long long)r.scheduledUs,(unsigned long long)r.publishedUs,
      (long)r.counts[0],(long)r.counts[1],(unsigned long)r.conversion[0],(unsigned long)r.conversion[1],(unsigned long long)r.acquiredUs[0],(unsigned long long)r.acquiredUs[1],r.validMask,r.freshMask);
}
void publishRow_() {
  const uint64_t current=now_();
  if(current<s_case.nextRowUs)return;
  const uint64_t missed=(current-s_case.nextRowUs)/2000;
  s_case.missedRows+=missed;
  SpiProbeRow row;row.index=s_case.rows+1;row.scheduledUs=s_case.nextRowUs+missed*2000;
  s_case.nextRowUs+=(missed+1)*2000;
  AnalogInputManager::beginSample();
  for(uint8_t i=0;i<2;++i) {
    const uint8_t ain=i?4:0;
    if(AnalogInputManager::readCounts(ain,row.counts[i]))row.validMask|=1U<<i;
    const auto use=AnalogInputManager::probeLastRow(ain);
    row.conversion[i]=use.sequence;row.acquiredUs[i]=use.afterReadUs;
    if(use.valid && use.fresh)row.freshMask|=1U<<i;
  }
  AnalogInputManager::endSample();row.publishedUs=now_();
  s_case.rowLedger.publish(row);++s_case.rows;
}
bool ownerTransfer_(uint8_t adc,uint8_t step) {
  if(!AnalogInputManager::probeTransferStep(adc,step,true,s_case.ownerRows)) {
    ++s_case.sequenceFailures;finish_("failed","adc_step_failed");return false;
  }
  ++s_case.sequenceCounts[adc][step];
  if(step==1)s_case.ownerStartedUs[adc]=now_();
  if(step==2 && s_case.ownerRows) {
    const uint64_t current=now_();
    if(s_case.lastOwnerReadUs[adc])TimingStats_record(s_case.ownerReadGap[adc],current-s_case.lastOwnerReadUs[adc]);
    s_case.lastOwnerReadUs[adc]=current;
  }
  s_case.ownerStep[adc]=(step+1)%3;return true;
}
void emit_(const char* outcome,const char* reason,bool stopped) {
  const auto adc=AnalogInputManager::probeTimingSnapshot();
  const auto drdy=AnalogInputManager::probeDrdySnapshot();
  const auto bus=SharedSpiBus::probeSnapshot();
  static const SpiProbeTransport::Stats empty;
  const auto& t=s_case.transportAttempted?SpiProbeTransport::stats():empty;
  Serial.printf("{\"schema\":\"bodaqs.spi-probe.v14\",\"type\":\"case\",\"case_id\":%lu,\"outcome\":\"%s\",\"reason\":\"%s\",",
      (unsigned long)s_case.id,outcome,reason);
  Serial.printf("\"artifacts\":{\"logger_build\":\"%s\",\"master_build\":\"external-manifest\",\"protocol\":1},",BODAQS_SPI_PROBE_BUILD);
  Serial.printf("\"profile\":{\"mode\":\"%s\",\"frame_bytes\":%u,\"requested_sck_hz\":%lu,\"actual_sck_hz\":null,\"actual_sck_basis\":\"unmeasured\",\"guard_us\":25,\"nodes\":%u,\"duration_ms\":%lu,\"row_hz\":500,\"ain\":[0,4],\"configured_sps\":[1000,1000],\"crc_mode\":\"%s\",\"start_interval_us\":%lu,\"retry_us\":%lu},",
      s_case.clockOnly?"owner_flow":s_case.pipelined?"owner_pipe":s_case.ownerRows?(s_case.bulk?"owner_rows":"owner_adc"):s_case.owner?"owner":s_case.workerControl?"workers":s_case.sequence?(s_case.selected?"selected":"shape"):(s_case.adc?(s_case.bulk?"mixed":"adc"):(s_case.switchMode?"switch":"bulk")),s_case.frame,(unsigned long)s_case.hz,s_case.nodes,(unsigned long)s_case.durationMs,s_case.cached?"cached":"legacy",(unsigned long)s_case.startIntervalUs,(unsigned long)(s_case.pipelined?s_case.retryUs:0));
  // Execution controls are explicit even when inactive for old modes.
  Serial.printf("\"execution\":{\"adc_mask\":%u,\"adc_core\":%u,\"cycle_us\":%lu,\"owner_core\":%u,\"window_started_us\":%llu,\"window_ended_us\":%llu,\"traffic\":[",
      s_case.adcMask,s_case.adcCore,(unsigned long)s_case.cycleUs,xPortGetCoreID(),
      (unsigned long long)s_case.traffic.startedUs,(unsigned long long)s_case.traffic.endedUs);
  bool trafficComma=false;
  for(const auto& p:s_case.traffic.participant)if(p.cs!=-1) {
    if(trafficComma)Serial.print(',');trafficComma=true;
    Serial.printf("{\"cs\":%d,\"core_mask\":%u,\"transfers\":%lu,\"lock_failures\":%lu,\"operations\":[%lu,%lu,%lu]}",
        p.cs,p.coreMask,(unsigned long)p.transfers,(unsigned long)p.lockFailures,
        (unsigned long)p.steps[0],(unsigned long)p.steps[1],(unsigned long)p.steps[2]);
  }
  Serial.print("]},");
  const auto& ledger=s_case.rowLedger;
  Serial.printf("\"row_publication\":{\"active\":%s,\"sink\":\"bounded_ram\",\"published\":%lu,\"valid_both\":%lu,\"fresh_both\":%lu,\"digest\":%lu,\"deadline_guard_us\":%lu,\"master_deferrals\":%lu,\"lag\":",
      s_case.ownerRows?"true":"false",(unsigned long)ledger.published,(unsigned long)ledger.validBoth,(unsigned long)ledger.freshBoth,
      (unsigned long)ledger.digest,(unsigned long)(s_case.ownerRows?kRowGuardUs:0),(unsigned long)s_case.deadlineDeferrals);
  summary_(ledger.lag);Serial.print(",\"read_gap\":[");summary_(s_case.ownerReadGap[0]);Serial.print(',');summary_(s_case.ownerReadGap[1]);
  Serial.print("],\"samples\":[");
  for(uint8_t i=0;i<4 && i<ledger.published;++i){if(i)Serial.print(',');row_(ledger.prefix[i]);}
  Serial.print("],\"last\":");if(ledger.published)row_(ledger.last);else Serial.print("null");Serial.print("},");
  Serial.printf("\"logger_cost\":{\"crc_algorithm\":\"%s\",\"cadence\":{\"active\":%s,\"cycle\":",
      BODAQS_SPI_PROBE_LOGGER_CRC_TABLE?"table":"bitwise",s_case.ownerRows?"true":"false");
  summary_(s_case.ownerCycle);
  Serial.print(",\"adc_ready_service\":");summary_(s_case.adcReadyService);
  Serial.print(",\"row_service\":");summary_(s_case.rowService);
  Serial.print(",\"adc_start_service\":");summary_(s_case.adcStartService);
  Serial.print(",\"transport_service\":");summary_(s_case.transportService);
  Serial.print(",\"dispatch_headroom\":");summary_(s_case.dispatchHeadroom);
  Serial.print(",\"decisions\":{");
  const char* decisions[]={"adc_only","row_reserve","cs_guard","pacing","dispatch","other"};
  for(uint8_t i=0;i<6;++i) {if(i)Serial.print(',');Serial.printf("\"%s\":",decisions[i]);summary_(s_case.decision[i]);}
  Serial.print("}}},");
  Serial.printf("\"elapsed_us\":%llu,\"rows\":%lu,\"missed_rows\":%lu,\"startup_included\":true,\"workers_stopped\":%s,",
      (unsigned long long)s_case.elapsedUs,(unsigned long)s_case.rows,(unsigned long)s_case.missedRows,stopped?"true":"false");
  Serial.printf("\"slots\":%lu,\"valid_responses\":%lu,\"unique_objects\":%lu,\"accepted_bytes\":%llu,\"retired_objects\":%lu,",
      (unsigned long)t.slots,(unsigned long)t.validResponses,(unsigned long)t.uniqueObjects,(unsigned long long)t.acceptedBytes,(unsigned long)t.retiredObjects);
  Serial.printf("\"errors\":{\"transfer\":%lu,\"wire\":%lu,\"stale\":%lu,\"duplicate\":%lu,\"accept\":%lu,\"commands\":%lu},\"timing\":{\"slot\":",
      (unsigned long)t.transferErrors,(unsigned long)t.wireErrors,(unsigned long)t.stale,(unsigned long)t.duplicates,(unsigned long)t.acceptErrors,(unsigned long)s_case.commandErrors);
  summary_(t.slot);Serial.print(",\"guard\":");summary_(t.guard);Serial.print(",\"encode\":");summary_(t.encode);Serial.print(",\"decode\":");summary_(t.decode);
  Serial.print("},\"spi\":[");
  bool comma=false;
  for(const auto& p:bus.participant) {
    if(!p.transfers && !p.lockFailures)continue;
    if(comma)Serial.print(',');comma=true;
    Serial.printf("{\"cs\":%d,\"transfers\":%lu,\"bytes\":%llu,\"lock_failures\":%lu,\"lock_wait\":",p.csPin,(unsigned long)p.transfers,(unsigned long long)p.bytes,(unsigned long)p.lockFailures);
    summary_(p.lockWait);Serial.print(",\"ownership\":");summary_(p.ownership);Serial.print('}');
  }
  Serial.print("],\"adc\":[");
  for(uint8_t i=0;i<2;++i) {
    if(i)Serial.print(',');
    const auto& a=adc.adc[i];const auto& c=a.channel[0];const auto& d=drdy.adc[i];
    Serial.printf("{\"index\":%u,\"acquire_ok\":%lu,\"acquire_fail\":%lu,\"fresh\":%lu,\"reused\":%lu,\"no_sample\":%lu,\"uses\":%lu,\"after_read_cache_age\":",i,(unsigned long)c.acquireOk,(unsigned long)c.acquireFail,(unsigned long)c.rowFresh,(unsigned long)c.rowReused,(unsigned long)c.rowNoSample,(unsigned long)c.rowUses);
    summary_(c.rowAgeUs);
    Serial.printf(",\"drdy_observed\":%lu,\"drdy_paired\":%lu,\"drdy_missing\":%lu,\"drdy_extra\":%lu,\"drdy_unpaired\":%lu,\"drdy_pre_start\":%lu,\"drdy_to_read_attempt\":",(unsigned long)d.observed,(unsigned long)d.paired,(unsigned long)d.missing,(unsigned long)d.extra,(unsigned long)d.unpaired,(unsigned long)d.preStart);
    summary_(d.toReadAttempt);Serial.print(",\"drdy_to_read_end\":");summary_(d.toReadEnd);
    Serial.printf(",\"wait_timeouts\":%lu,\"config\":",(unsigned long)a.waitTimeouts);summary_(a.configUs);
    Serial.print(",\"start\":");summary_(a.startUs);Serial.print(",\"wait\":");summary_(a.waitUs);
    Serial.print(",\"read\":");summary_(a.readUs);Serial.print(",\"total\":");summary_(c.totalUs);
    Serial.print(",\"async_loop\":");summary_(a.asyncLoopUs);Serial.print('}');
  }
  Serial.printf("],\"master\":{\"measured\":%s,\"before\":",t.masterMeasured?"true":"false");array_(t.masterBefore);
  Serial.print(",\"after\":");array_(t.masterAfter);
  Serial.printf(",\"adapter_measured\":%s,\"adapter_before\":",t.adapterMeasured?"true":"false");array_(t.adapterBefore);
  Serial.print(",\"adapter_after\":");array_(t.adapterAfter);
  Serial.printf(",\"diagnostic_measured\":%s,\"diagnostic_before\":",t.diagnosticMeasured?"true":"false");array_(t.diagnosticBefore);
  Serial.print(",\"diagnostic_after\":");array_(t.diagnosticAfter);
  Serial.printf(",\"processing_measured\":%s,\"processing_before\":",t.processingMeasured?"true":"false");array_(t.processingBefore);
  Serial.print(",\"processing_after\":");array_(t.processingAfter);
  Serial.print(",\"processing_meta_before\":");array_(t.processingMetaBefore);
  Serial.print(",\"processing_meta_after\":");array_(t.processingMetaAfter);
  Serial.printf(",\"receive_measured\":%s,\"receive_before\":",t.receiveMeasured?"true":"false");array_(t.receiveBefore);
  Serial.print(",\"receive_after\":");array_(t.receiveAfter);
  Serial.print(",\"turnover_before\":");array_(t.turnoverBefore);
  Serial.print(",\"turnover_after\":");array_(t.turnoverAfter);
  Serial.printf(",\"flow_measured\":%s,\"flow_before\":",t.flowMeasured?"true":"false");array_(t.flowBefore);
  Serial.print(",\"flow_after\":");array_(t.flowAfter);
  Serial.printf(",\"early_measured\":%s,\"early_before\":",t.earlyMeasured?"true":"false");array_(t.earlyBefore);
  Serial.print(",\"early_after\":");array_(t.earlyAfter);
  Serial.printf(",\"reply_trace\":{\"measured\":%s,\"read_complete\":%s,\"header\":",t.traceMeasured?"true":"false",t.traceReadComplete?"true":"false");
  array_(t.traceHeader);Serial.print(",\"records\":[");
  for(uint8_t i=0;i<t.traceCount;++i) {
    if(i)Serial.print(',');Serial.print('[');
    for(uint8_t j=0;j<20;++j){if(j)Serial.print(',');Serial.printf("%lu",(unsigned long)t.traceRecords[i][j]);}
    Serial.print(']');
  }
  Serial.print("]}");
  Serial.printf(",\"timing_measured\":%s,\"timing_scope\":\"%s\"},",t.diagnosticMeasured?"true":"false",t.diagnosticMeasured?"software_observations":"unmeasured");
  Serial.printf("\"request_window\":{\"active\":%s,\"limit\":%u,\"retry_us\":%u,\"retry_limit\":%u,\"new_requests\":%lu,\"retry_requests\":%lu,\"clock_requests\":%lu,\"retry_exhausted\":%lu,\"pending\":%lu,\"high_water\":%lu,\"reply_age\":",
      s_case.pipelined?"true":"false",s_case.pipelined?4:0,s_case.pipelined?s_case.retryUs:0,s_case.pipelined?8:0,
      (unsigned long)t.newRequests,(unsigned long)t.retryRequests,(unsigned long)t.clockRequests,(unsigned long)t.retryExhausted,
      (unsigned long)t.pendingRequests,(unsigned long)t.pendingHighWater);
  summary_(t.replyAge);Serial.print("},");
  Serial.print("\"diagnostics\":{\"decode_counts\":[");
  for(uint8_t i=0;i<9;++i){if(i)Serial.print(',');Serial.printf("%lu",(unsigned long)t.decodeCounts[i]);}
  Serial.print("],\"failure_samples\":[");
  for(uint8_t i=0;i<t.failureCount;++i) {
    if(i)Serial.print(',');const auto& f=t.failures[i];const auto& b=f.bus;
    Serial.printf("{\"reason\":%u,\"slot\":%lu,\"frame_bytes\":%u,\"rx_hex\":\"",f.reason,(unsigned long)f.slot,f.frameBytes);
    for(uint16_t byte=0;byte<f.frameBytes;++byte)Serial.printf("%02x",f.rx[byte]);
    Serial.printf("\",\"request\":{\"opcode\":%u,\"node\":%u,\"fragment\":%u,\"profile\":%u,\"case_id\":%lu,\"object_id\":%lu,\"logical_crc\":%lu},",f.opcode,f.node,f.fragment,f.profile,(unsigned long)f.caseId,(unsigned long)f.objectId,(unsigned long)f.logicalCrc);
    Serial.printf("\"bus\":{\"sequence\":%lu,\"cs\":%d,\"previous_valid\":%s,\"previous_cs\":%d,\"previous_release_us\":%lu,\"cs_assert_us\":%lu,\"cs_release_us\":%lu,\"previous_operation\":",(unsigned long)b.sequence,b.cs,b.previousValid?"true":"false",b.previousCs,(unsigned long)b.previousReleaseUs,(unsigned long)b.csAssertUs,(unsigned long)b.csReleaseUs);
    operation_(b.previousOperation);Serial.print("}}");
  }
  Serial.printf("],\"failure_samples_omitted\":%lu,\"by_previous_cs\":[",(unsigned long)t.failureSamplesOmitted);
  comma=false;for(const auto& p:t.byPreviousCs)if(p.used){if(comma)Serial.print(',');comma=true;Serial.printf("{\"cs\":%d,\"responses\":%lu,\"decode_failures\":%lu}",p.cs,(unsigned long)p.responses,(unsigned long)p.decodeFailures);}
  Serial.print("],\"by_previous_operation\":[");comma=false;
  for(const auto& p:t.byPreviousOperation)if(p.used) {
    if(comma)Serial.print(',');comma=true;
    Serial.printf("{\"cs\":%d,\"responses\":%lu,\"decode_failures\":%lu,\"operation\":",p.cs,(unsigned long)p.responses,(unsigned long)p.decodeFailures);
    operation_(p.operation);Serial.print('}');
  }
  Serial.printf("],\"operation_buckets_omitted\":%lu,\"sequence\":{\"active\":%s,\"worker_start_requested\":%s,\"failures\":%lu,\"timeouts\":%lu,\"operations\":[",
      (unsigned long)t.operationBucketsOmitted,s_case.sequence?"true":"false",s_case.workerStartRequested?"true":"false",(unsigned long)s_case.sequenceFailures,(unsigned long)s_case.sequenceTimeouts);
  for(uint8_t i=0;i<2;++i){if(i)Serial.print(',');Serial.printf("[%lu,%lu,%lu]",(unsigned long)s_case.sequenceCounts[i][0],(unsigned long)s_case.sequenceCounts[i][1],(unsigned long)s_case.sequenceCounts[i][2]);}
  Serial.print("]}");
  Serial.print(",\"timing\":{\"validate\":");summary_(t.validate);
  Serial.print(",\"expected_crc\":");summary_(t.expectedCrc);
  Serial.print(",\"object_crc\":");summary_(t.objectCrc);
  Serial.print(",\"iteration\":");summary_(t.iteration);
  Serial.print(",\"request_interval\":");summary_(t.requestInterval);
  Serial.printf("},\"expected_crc_calls\":%lu,\"pacing_deferred\":%lu,\"switch_transfers\":%lu,\"switch_failures\":%lu}}\n",(unsigned long)t.expectedCrc.count,(unsigned long)t.pacingDeferred,(unsigned long)t.switchTransfers,(unsigned long)t.switchFailures);
}
void finish_(const char* outcome,const char* reason) {
  s_case.elapsedUs=s_case.startUs?now_()-s_case.startUs:0;
  if(s_case.active && (s_case.adc || s_case.ownerRows)) {
    const uint64_t requestedEnd=s_case.startUs+static_cast<uint64_t>(s_case.durationMs)*1000;
    const uint64_t actualEnd=s_case.startUs+s_case.elapsedUs;
    const uint64_t end=actualEnd<requestedEnd?actualEnd:requestedEnd;
    // Midpoints strictly inside the finite [start,end) observation window.
    // STOP at a midpoint has not observed that instant and counts no new row.
    if(s_case.nextRowUs<end)s_case.missedRows+=(end-1-s_case.nextRowUs)/2000+1;
  }
  if(s_case.trafficStarted)s_case.traffic=SharedSpiBus::probeTrafficEnd();
  s_case.active=false;
  if(s_case.ownerRows)AnalogInputManager::probeOwnerEnd();
  if(s_case.workerStartRequested)AnalogInputManager::onLoggingStop();
  const bool stopped=AnalogInputManager::probeWorkersStopped();
  if(!stopped) {s_blocked=true;outcome="failed";reason="adc_stop_incomplete_reboot_required";}
  if(s_case.workerControl && stopped && strcmp(outcome,"complete")==0) {
    const auto adc=AnalogInputManager::probeTimingSnapshot();
    for(uint8_t i=0;i<2;++i)if(s_case.adcMask&(1U<<i)) {
      bool read=false;
      for(const auto& p:s_case.traffic.participant)
        if(p.cs==s_board->external_adcs[i].cs_pin && p.steps[2])read=true;
      if(!read || adc.adc[i].channel[0].acquireFail || adc.adc[i].waitTimeouts) {
        outcome="failed";reason="adc_worker_incomplete";
      }
    }
  }
  if(s_case.transportAttempted && !SpiProbeTransport::stop(stopped)) {s_blocked=true;outcome="failed";reason="master_stop_unconfirmed_reboot_required";}
  emit_(outcome,reason,stopped);
}
bool decimal_(const char* token,uint32_t& value) {
  if(!token || !*token)return false;
  uint64_t n=0;
  for(const char* p=token;*p;++p) {if(*p<'0'||*p>'9')return false;n=n*10+(*p-'0');if(n>UINT32_MAX)return false;}
  value=static_cast<uint32_t>(n);return true;
}
}

namespace SpiMeasurementProbe {
void begin(const board::BoardProfile& board) {
  s_board=&board;
  // Every shared peripheral is deselected before the first ADC reset command.
  for(uint8_t i=0;i<board.spi.cs_count && i<8;++i)if(board.spi.cs_pins[i]>=0) {
    pinMode(static_cast<uint8_t>(board.spi.cs_pins[i]),OUTPUT);
    digitalWrite(static_cast<uint8_t>(board.spi.cs_pins[i]),HIGH);
  }
  AnalogInputManager::begin(board);
  s_cfg.sampleRateHz=500;s_cfg.sensorN=2;
  for(uint8_t i=0;i<2;++i) {s_cfg.sensors[i].type=SensorType::AnalogPot;s_cfg.sensors[i].mutedDefault=false;}
  char ain0[]="sensor0.ain=0",ain4[]="sensor1.ain=4";
  s_ready=ConfigManager::parseLine(ain0,s_cfg) && ConfigManager::parseLine(ain4,s_cfg) &&
      AnalogInputManager::configureFromConfig(s_cfg,500)==500 && SharedSpiBus::ready() &&
      AnalogInputManager::activeChannelCount(0)==1 && AnalogInputManager::activeChannelCount(1)==1 &&
      AnalogInputManager::configuredDataRateSps(0)==1000 && AnalogInputManager::configuredDataRateSps(1)==1000;
  Serial.printf("{\"schema\":\"bodaqs.spi-probe.v14\",\"type\":\"ready\",\"ready\":%s,\"bench_only\":true,\"logger_build\":\"%s\"}\n",s_ready?"true":"false",BODAQS_SPI_PROBE_BUILD);
}
void command(const char* line) {
  if(!line)return;
  if(strcmp(line,"stop")==0) {if(s_case.active)finish_("stopped","command");else error_("idle");return;}
  if(s_case.active) {++s_case.commandErrors;return;}
  if(strcmp(line,"status")==0) {
    Serial.printf("{\"schema\":\"bodaqs.spi-probe.v14\",\"type\":\"status\",\"ready\":%s,\"blocked\":%s,\"logger_build\":\"%s\"}\n",s_ready?"true":"false",s_blocked?"true":"false",BODAQS_SPI_PROBE_BUILD);return;
  }
  if(!s_ready || !s_board) {error_("not_ready");return;}
  if(s_blocked || !AnalogInputManager::probeWorkersStopped()) {error_("reboot_required");return;}
  if(strlen(line)>=sizeof(s_line)) {error_("command_too_long");return;}
  char copy[sizeof(s_line)];strcpy(copy,line);
  char* tokens[14]={};char* save=nullptr;uint8_t n=0;
  for(char* t=strtok_r(copy," \t",&save);t && n<14;t=strtok_r(nullptr," \t",&save))tokens[n++]=t;
  uint32_t id=0,frame=0,hz=0,nodes=0,duration=0,interval=0,mask=3,core=0,cycle=0,retry=5000;
  const bool ownerRowsMode=n>=3 && (strcmp(tokens[2],"owner_flow")==0 || strcmp(tokens[2],"owner_pipe")==0 || strcmp(tokens[2],"owner_rows")==0 || strcmp(tokens[2],"owner_adc")==0);
  const bool pipelineMode=n>=3 && (strcmp(tokens[2],"owner_flow")==0 || strcmp(tokens[2],"owner_pipe")==0);
  const bool ownerMode=ownerRowsMode || (n>=3 && strcmp(tokens[2],"owner")==0);
  const bool executionMode=ownerMode || (n>=3 && strcmp(tokens[2],"workers")==0);
  if((n!=7 && n!=9 && n!=12 && n!=13) || strcmp(tokens[0],"case") || !decimal_(tokens[1],id) || !id ||
      !decimal_(tokens[3],frame) || (frame!=64 && frame!=128 && frame!=256) ||
      !decimal_(tokens[4],hz) || (hz!=8000000 && hz!=16000000) ||
      !decimal_(tokens[5],nodes) || nodes<1 || nodes>4 ||
      !decimal_(tokens[6],duration) || duration<100 || duration>3600000 ||
      (strcmp(tokens[2],"adc") && strcmp(tokens[2],"bulk") && strcmp(tokens[2],"mixed") && strcmp(tokens[2],"switch") && strcmp(tokens[2],"shape") && strcmp(tokens[2],"selected") && strcmp(tokens[2],"owner") && strcmp(tokens[2],"workers") && strcmp(tokens[2],"owner_rows") && strcmp(tokens[2],"owner_adc") && strcmp(tokens[2],"owner_pipe") && strcmp(tokens[2],"owner_flow")) ||
      (n>=9 && ((strcmp(tokens[7],"legacy") && strcmp(tokens[7],"cached")) || !decimal_(tokens[8],interval) || interval>5000)) ||
      (executionMode!=(n>=12)) ||
      (n>=12 && (!decimal_(tokens[9],mask) || mask<1 || mask>3 ||
                 !decimal_(tokens[10],core) || core>1 || !decimal_(tokens[11],cycle) ||
                 (cycle && cycle<1500) || cycle>20000 ||
                 (ownerMode && core!=static_cast<uint32_t>(xPortGetCoreID())))) ||
      (ownerRowsMode && (mask!=3 || cycle!=0)) ||
      (n==13 && (!pipelineMode || !decimal_(tokens[12],retry) || (retry!=5000 && retry!=10000 && retry!=20000)))) {error_("invalid_profile");return;}
  if(id<=s_lastCaseId) {error_("non_increasing_case_id");return;}
  // A valid start attempt owns its ID even when rail/worker/peer startup fails.
  s_lastCaseId=id;
  s_case=Case{};s_case.id=id;s_case.frame=frame;s_case.hz=hz;s_case.nodes=nodes;s_case.durationMs=duration;
  s_case.retryUs=retry;
  s_case.clockOnly=strcmp(tokens[2],"owner_flow")==0;
  s_case.pipelined=s_case.clockOnly || strcmp(tokens[2],"owner_pipe")==0;
  s_case.ownerRows=s_case.pipelined || strcmp(tokens[2],"owner_rows")==0 || strcmp(tokens[2],"owner_adc")==0;
  s_case.owner=strcmp(tokens[2],"owner")==0 || s_case.ownerRows;s_case.workerControl=strcmp(tokens[2],"workers")==0;
  s_case.adcMask=mask;s_case.adcCore=core;s_case.cycleUs=cycle;
  if(!AnalogInputManager::probeWorkerProfile(mask,core,cycle)) {error_("worker_profile_busy");return;}
  s_case.switchMode=strcmp(tokens[2],"switch")==0;
  s_case.sequence=strcmp(tokens[2],"shape")==0 || strcmp(tokens[2],"selected")==0 || s_case.owner;
  s_case.selected=strcmp(tokens[2],"selected")==0 || s_case.owner;
  s_case.cached=n>=9 && strcmp(tokens[7],"cached")==0;s_case.startIntervalUs=interval;
  s_case.adc=strcmp(tokens[2],"adc")==0 || strcmp(tokens[2],"mixed")==0;s_case.bulk=strcmp(tokens[2],"adc")!=0 && strcmp(tokens[2],"owner_adc")!=0;
  AnalogInputManager::configureFromConfig(s_cfg,500);
  SharedSpiBus::probeReset();
  if((s_case.adc || s_case.selected || s_case.workerControl) && (PowerManager::analogRailFaultActive() || PowerManager::analogRailFaultLatched() || !PowerManager::analogRailEnabled())) {emit_("failed","analog_rail_fault",true);return;}
  if(s_case.bulk) {
    s_case.transportAttempted=true;
    if(!SpiProbeTransport::begin(*s_board,id,frame,hz,nodes,s_case.cached?SpiProbeTransport::CrcMode::Cached:SpiProbeTransport::CrcMode::Legacy,interval,s_case.switchMode,s_case.pipelined,s_case.clockOnly,s_case.retryUs)) {finish_("failed","master_entry_failed");return;}
  }
  if(s_case.adc || s_case.workerControl) {
    s_case.workerStartRequested=true;
    AnalogInputManager::onLoggingStart();
    const uint64_t timeout=now_()+100000;
    while(!AnalogInputManager::probeWorkersRunning() && now_()<timeout)delay(1);
    if(!AnalogInputManager::probeWorkersRunning()) {finish_("failed","async_start_failed");return;}
  }
  if(s_case.ownerRows && !AnalogInputManager::probeOwnerBegin()) {finish_("failed","owner_warmup_failed");return;}
  // Phase rows at the midpoint of each 2 ms interval. Startup finishes before
  // the first row, and a 10 s half-open window has 5000 serviceable deadlines.
  SharedSpiBus::probeTrafficBegin();s_case.trafficStarted=true;
  s_case.startUs=now_();s_case.nextRowUs=s_case.startUs+1000;s_case.active=true;
}
void loop() {
  // Bound serial work per iteration so a sender cannot starve row scheduling.
  for(uint8_t consumed=0;consumed<32 && Serial.available();++consumed) {
    const char ch=static_cast<char>(Serial.read());
    if(ch=='\r')continue;
    if(ch=='\n') {
      if(s_lineOverflow) {if(s_case.active)++s_case.commandErrors;else error_("command_too_long");}
      else {s_line[s_lineLength]='\0';command(s_line);}
      s_lineLength=0;s_lineOverflow=false;
    } else if(s_lineLength+1<sizeof(s_line))s_line[s_lineLength++]=ch;
    else s_lineOverflow=true;
  }
  if(!s_case.active) {delay(1);return;}
  const uint64_t now=now_();
  if(now-s_case.startUs>=static_cast<uint64_t>(s_case.durationMs)*1000) {
    // Account remaining midpoints inside the finite window. Do not invent
    // catch-up reads after the timed window ended.
    if(s_case.sequence && (((s_case.adcMask&1) && !s_case.sequenceCounts[0][2]) || ((s_case.adcMask&2) && !s_case.sequenceCounts[1][2])))
      finish_("failed","adc_sequence_incomplete");
    else finish_("complete","duration");
    return;
  }
  if(s_case.ownerRows) {
    if(PowerManager::analogRailFaultActive() || PowerManager::analogRailFaultLatched() || !PowerManager::analogRailEnabled()) {finish_("failed","analog_rail_fault");return;}
    const uint64_t cycleStart=now_();
    // Drain completed conversions first, then publish the due row before starts.
    for(uint8_t adc=0;adc<2;++adc)if(s_case.ownerStep[adc]==2) {
      if(now_()-s_case.ownerStartedUs[adc]>6000) {++s_case.sequenceTimeouts;finish_("failed","adc_ready_timeout");return;}
      if(AnalogInputManager::probeDataReady(adc) && !ownerTransfer_(adc,2))return;
    }
    // ADC work may cross the finite window: never fabricate an end-of-case row.
    if(now_()>=s_case.startUs+static_cast<uint64_t>(s_case.durationMs)*1000) {finish_("complete","duration");return;}
    const uint64_t readyEnd=now_();
    publishRow_();
    const uint64_t rowEnd=now_();
    for(uint8_t adc=0;adc<2;++adc)if(s_case.ownerStep[adc]==0) {
      // Bounded WREG/START pair, using the same physical commands as workers.
      if(!ownerTransfer_(adc,0) || !ownerTransfer_(adc,1))return;
    }
    const uint64_t startEnd=now_();
    uint8_t decision=0;
    bool healthy=true;
    if(s_case.bulk) {
      const uint64_t current=now_();
      if(current>=s_case.nextRowUs || s_case.nextRowUs-current<=kRowGuardUs) {++s_case.deadlineDeferrals;decision=1;}
      else {
        const auto& before=SpiProbeTransport::stats();
        const uint32_t slots=before.slots,guard=before.csGuardDeferred,pace=before.intervalDeferred;
        SpiProbeTransport::tick();
        const auto& after=SpiProbeTransport::stats();
        decision=after.slots!=slots?4:after.csGuardDeferred!=guard?2:after.intervalDeferred!=pace?3:5;
        if(decision==4)TimingStats_record(s_case.dispatchHeadroom,s_case.nextRowUs-current);
        healthy=SpiProbeTransport::healthy();
      }
    }
    const uint64_t end=now_();
    TimingStats_record(s_case.adcReadyService,readyEnd-cycleStart);
    TimingStats_record(s_case.rowService,rowEnd-readyEnd);
    TimingStats_record(s_case.adcStartService,startEnd-rowEnd);
    if(s_case.bulk && decision!=1)TimingStats_record(s_case.transportService,end-startEnd);
    TimingStats_record(s_case.ownerCycle,end-cycleStart);
    TimingStats_record(s_case.decision[decision],end-cycleStart);
    if(!healthy)finish_("failed","bulk_fault_or_stalled");
    return;
  }
  if(s_case.adc || s_case.workerControl || s_case.owner) {
    if(PowerManager::analogRailFaultActive() || PowerManager::analogRailFaultLatched()) {finish_("failed","analog_rail_fault");return;}
    if(s_case.adc && now>=s_case.nextRowUs) {
      const uint64_t missed=(now-s_case.nextRowUs)/2000;
      s_case.missedRows+=missed;s_case.nextRowUs+=(missed+1)*2000;
      int32_t counts;
      AnalogInputManager::beginSample();
      (void)AnalogInputManager::readCounts(0,counts);(void)AnalogInputManager::readCounts(4,counts);
      AnalogInputManager::endSample();++s_case.rows;
    }
  }
  if(s_case.bulk) {
    if(s_case.owner) {
      // Independent conversions; at most one ADC operation per owner iteration.
      // Master tick below always runs, including while either ADC converts.
      for(uint8_t checked=0;checked<2;++checked) {
        const uint8_t adc=(s_case.ownerCursor+checked)&1;
        if(!(s_case.adcMask&(1U<<adc)))continue;
        const uint8_t step=s_case.ownerStep[adc];const uint64_t current=now_();
        if(step==0 && current<s_case.ownerNextUs[adc])continue;
        if(step==2) {
          if(current-s_case.ownerStartedUs[adc]>6000) {++s_case.sequenceTimeouts;finish_("failed","adc_ready_timeout");return;}
          if(!AnalogInputManager::probeDataReady(adc))continue;
        }
        if(!AnalogInputManager::probeTransferStep(adc,step,true)) {++s_case.sequenceFailures;finish_("failed","adc_step_failed");return;}
        ++s_case.sequenceCounts[adc][step];
        if(step==0)s_case.ownerNextUs[adc]=current+s_case.cycleUs;
        if(step==1)s_case.ownerStartedUs[adc]=now_();
        s_case.ownerStep[adc]=(step+1)%3;s_case.ownerCursor=adc^1;break;
      }
    }
    if(s_case.sequence && !s_case.owner && SpiProbeTransport::requestDue()) {
      if(s_case.selected && (PowerManager::analogRailFaultActive() || PowerManager::analogRailFaultLatched())) {finish_("failed","analog_rail_fault");return;}
      if(s_case.sequenceStep==2) {
        const uint64_t waited=now_()-s_case.sequenceStartedUs;
        if(waited>6000) {++s_case.sequenceTimeouts;finish_("failed","adc_ready_timeout");return;}
        // A conversion-sized delay in the unselected control; selected mode
        // polls the real dedicated DRDY without an ISR or ADC worker.
        if(s_case.selected?!AnalogInputManager::probeDataReady(s_case.sequenceAdc):waited<1000)return;
      }
      if(!AnalogInputManager::probeTransferStep(s_case.sequenceAdc,s_case.sequenceStep,s_case.selected)) {
        ++s_case.sequenceFailures;finish_("failed","adc_step_failed");return;
      }
      ++s_case.sequenceCounts[s_case.sequenceAdc][s_case.sequenceStep];
      if(s_case.sequenceStep==1)s_case.sequenceStartedUs=now_();
      if(++s_case.sequenceStep==3){s_case.sequenceStep=0;s_case.sequenceAdc^=1;}
    }
    SpiProbeTransport::tick();
    if(!SpiProbeTransport::healthy())finish_("failed","bulk_fault_or_stalled");
  }
}
}
#endif
