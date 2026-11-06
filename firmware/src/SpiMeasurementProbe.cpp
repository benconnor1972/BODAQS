#include "SpiMeasurementProbe.h"
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
#include "AnalogInputManager.h"
#include "SharedSpiBus.h"
#include "ConfigManager.h"
#include "PowerManager.h"
#include "SpiProbeTransport.h"
#include "esp_timer.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <limits.h>

#ifndef BODAQS_SPI_PROBE_BUILD
#define BODAQS_SPI_PROBE_BUILD "spi-probe-v1 " __DATE__ " " __TIME__
#endif

namespace {
const board::BoardProfile* s_board=nullptr;
LoggerConfig s_cfg;
struct Case {
  uint32_t id=0,hz=8000000,durationMs=1000;
  uint16_t frame=64;
  uint8_t nodes=1;
  bool adc=false,bulk=false,active=false,transportAttempted=false;
  uint64_t startUs=0,nextRowUs=0,elapsedUs=0;
  uint32_t rows=0,missedRows=0,commandErrors=0;
} s_case;
bool s_ready=false,s_blocked=false;
uint32_t s_lastCaseId=0;
char s_line[96];
uint8_t s_lineLength=0;
bool s_lineOverflow=false;

uint64_t now_() { return static_cast<uint64_t>(esp_timer_get_time()); }
void error_(const char* reason) {
  Serial.printf("{\"schema\":\"bodaqs.spi-probe.v1\",\"type\":\"error\",\"reason\":\"%s\"}\n",reason);
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
void emit_(const char* outcome,const char* reason,bool stopped) {
  const auto adc=AnalogInputManager::probeTimingSnapshot();
  const auto drdy=AnalogInputManager::probeDrdySnapshot();
  const auto bus=SharedSpiBus::probeSnapshot();
  const SpiProbeTransport::Stats empty;
  const auto& t=s_case.transportAttempted?SpiProbeTransport::stats():empty;
  Serial.printf("{\"schema\":\"bodaqs.spi-probe.v1\",\"type\":\"case\",\"case_id\":%lu,\"outcome\":\"%s\",\"reason\":\"%s\",",
      (unsigned long)s_case.id,outcome,reason);
  Serial.printf("\"artifacts\":{\"logger_build\":\"%s\",\"master_build\":\"external-manifest\",\"protocol\":1},",BODAQS_SPI_PROBE_BUILD);
  Serial.printf("\"profile\":{\"mode\":\"%s\",\"frame_bytes\":%u,\"requested_sck_hz\":%lu,\"actual_sck_hz\":null,\"actual_sck_basis\":\"unmeasured\",\"guard_us\":25,\"nodes\":%u,\"duration_ms\":%lu,\"row_hz\":500,\"ain\":[0,4],\"configured_sps\":[1000,1000]},",
      s_case.adc?(s_case.bulk?"mixed":"adc"):"bulk",s_case.frame,(unsigned long)s_case.hz,s_case.nodes,(unsigned long)s_case.durationMs);
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
    if(p.csPin<0)continue;
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
  Serial.println(",\"timing_measured\":false,\"timing_scope\":\"unmeasured\"}}");
}
void finish_(const char* outcome,const char* reason) {
  s_case.elapsedUs=s_case.startUs?now_()-s_case.startUs:0;
  if(s_case.active && s_case.adc) {
    const uint64_t requestedEnd=s_case.startUs+static_cast<uint64_t>(s_case.durationMs)*1000;
    const uint64_t actualEnd=s_case.startUs+s_case.elapsedUs;
    const uint64_t end=actualEnd<requestedEnd?actualEnd:requestedEnd;
    if(s_case.nextRowUs<=end)s_case.missedRows+=(end-s_case.nextRowUs)/2000+1;
  }
  s_case.active=false;
  if(s_case.adc)AnalogInputManager::onLoggingStop();
  const bool stopped=AnalogInputManager::probeWorkersStopped();
  if(!stopped) {s_blocked=true;outcome="failed";reason="adc_stop_incomplete_reboot_required";}
  if(s_case.transportAttempted && !SpiProbeTransport::stop()) {s_blocked=true;outcome="failed";reason="master_stop_unconfirmed_reboot_required";}
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
  Serial.printf("{\"schema\":\"bodaqs.spi-probe.v1\",\"type\":\"ready\",\"ready\":%s,\"bench_only\":true}\n",s_ready?"true":"false");
}
void command(const char* line) {
  if(!line)return;
  if(strcmp(line,"stop")==0) {if(s_case.active)finish_("stopped","command");else error_("idle");return;}
  if(s_case.active) {++s_case.commandErrors;return;}
  if(strcmp(line,"status")==0) {
    Serial.printf("{\"schema\":\"bodaqs.spi-probe.v1\",\"type\":\"status\",\"ready\":%s,\"blocked\":%s}\n",s_ready?"true":"false",s_blocked?"true":"false");return;
  }
  if(!s_ready || !s_board) {error_("not_ready");return;}
  if(s_blocked || !AnalogInputManager::probeWorkersStopped()) {error_("reboot_required");return;}
  if(strlen(line)>=sizeof(s_line)) {error_("command_too_long");return;}
  char copy[sizeof(s_line)];strcpy(copy,line);
  char* tokens[8]={};char* save=nullptr;uint8_t n=0;
  for(char* t=strtok_r(copy," \t",&save);t && n<8;t=strtok_r(nullptr," \t",&save))tokens[n++]=t;
  uint32_t id=0,frame=0,hz=0,nodes=0,duration=0;
  if(n!=7 || strcmp(tokens[0],"case") || !decimal_(tokens[1],id) || !id ||
      !decimal_(tokens[3],frame) || (frame!=64 && frame!=128 && frame!=256) ||
      !decimal_(tokens[4],hz) || (hz!=8000000 && hz!=16000000) ||
      !decimal_(tokens[5],nodes) || nodes<1 || nodes>4 ||
      !decimal_(tokens[6],duration) || duration<100 || duration>3600000 ||
      (strcmp(tokens[2],"adc") && strcmp(tokens[2],"bulk") && strcmp(tokens[2],"mixed"))) {error_("invalid_profile");return;}
  if(id<=s_lastCaseId) {error_("non_increasing_case_id");return;}
  // A valid start attempt owns its ID even when rail/worker/peer startup fails.
  s_lastCaseId=id;
  s_case=Case{};s_case.id=id;s_case.frame=frame;s_case.hz=hz;s_case.nodes=nodes;s_case.durationMs=duration;
  s_case.adc=strcmp(tokens[2],"bulk")!=0;s_case.bulk=strcmp(tokens[2],"adc")!=0;
  AnalogInputManager::configureFromConfig(s_cfg,500);
  SharedSpiBus::probeReset();
  if(s_case.adc && (PowerManager::analogRailFaultActive() || PowerManager::analogRailFaultLatched() || !PowerManager::analogRailEnabled())) {emit_("failed","analog_rail_fault",true);return;}
  if(s_case.bulk) {
    s_case.transportAttempted=true;
    if(!SpiProbeTransport::begin(*s_board,id,frame,hz,nodes)) {finish_("failed","master_entry_failed");return;}
  }
  if(s_case.adc) {
    AnalogInputManager::onLoggingStart();
    const uint64_t timeout=now_()+100000;
    while(!AnalogInputManager::probeWorkersRunning() && now_()<timeout)delay(1);
    if(!AnalogInputManager::probeWorkersRunning()) {finish_("failed","async_start_failed");return;}
  }
  s_case.startUs=now_();s_case.nextRowUs=s_case.startUs+2000;s_case.active=true;
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
    // Account every scheduled row through the finite window, including its last
    // deadline. Do not invent catch-up reads after the timed window ended.
    finish_("complete","duration");return;
  }
  if(s_case.adc) {
    if(PowerManager::analogRailFaultActive() || PowerManager::analogRailFaultLatched()) {finish_("failed","analog_rail_fault");return;}
    if(now>=s_case.nextRowUs) {
      const uint64_t missed=(now-s_case.nextRowUs)/2000;
      s_case.missedRows+=missed;s_case.nextRowUs+=(missed+1)*2000;
      int32_t counts;
      AnalogInputManager::beginSample();
      (void)AnalogInputManager::readCounts(0,counts);(void)AnalogInputManager::readCounts(4,counts);
      AnalogInputManager::endSample();++s_case.rows;
    }
  }
  if(s_case.bulk) {
    SpiProbeTransport::tick();
    if(!SpiProbeTransport::healthy())finish_("failed","bulk_fault_or_stalled");
  }
}
}
#endif
