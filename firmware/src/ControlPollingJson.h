#pragma once
#include "ControlPollingDiagnostics.h"
#if BODAQS_CONTROL_POLL_DIAGNOSTICS
#include <ArduinoJson.h>
namespace ControlPollingJson {
template<class T,size_t N> inline void values(JsonObject row,const char* key,const T (&items)[N]){
  auto a=row[key].to<JsonArray>();for(auto value:items)a.add(value);
}
inline void append(JsonDocument& document,bool retired,uint64_t context){
  using namespace ControlPollingDiagnostics;
  auto out=document["control_poll_timeline"].to<JsonObject>();out["version"]=1;
  const bool available=retired && memory.initialized && acquisition.context==context &&
      acquisition.originUs==memory.originUs;
  out["available"]=available;memory.frozen=true;
  if(!available)return;
  out["context"]=context;out["origin_us"]=memory.originUs;
  out["bin_us"]=RecordingTimelineDiagnostics::binUs;out["capacity"]=capacity;
  out["acquisition_used"]=acquisition.used;out["memory_used"]=memory.used;
  out["acquisition_overflow_events"]=acquisition.overflow;out["memory_overflow_events"]=memory.overflow;
  out["scope"]="MOSI_attempts_not_response_pairs_memory_point_samples_not_CPU_or_causality";
  auto rows=out["bins"].to<JsonArray>();
  const uint32_t used=acquisition.used>memory.used?acquisition.used:memory.used;
  for(uint32_t i=0;i<used;++i){
    auto row=rows.add<JsonObject>();row["index"]=i;const auto& b=acquisition.bins[i];
    values(row,"targets",b.targets);values(row,"reasons",b.reasons);values(row,"fetches",b.fetches);
    values(row,"pending_fetches",b.pendingFetches);values(row,"age_sum_ms",b.ageSumMs);values(row,"age_max_ms",b.ageMaxMs);
    values(row,"first_operation",b.firstOperation);values(row,"last_operation",b.lastOperation);
    values(row,"begins",b.begins);values(row,"matched",b.matched);values(row,"timeouts",b.timeouts);
    values(row,"matched_age_max_ms",b.matchedAgeMaxMs);
    auto op=row["last_opcode"].to<JsonArray>();auto page=row["last_page"].to<JsonArray>();
    for(unsigned n=0;n<4;++n){op.add(b.lastOpcode[n]);page.add(b.lastPage[n]);}
    const auto& m=memory.bins[i];auto mem=row["memory"].to<JsonObject>();
    mem["samples"]=m.samples;mem["elapsed_us"]=m.elapsedUs;
    mem["internal_free"]=m.internalFree;mem["internal_largest"]=m.internalLargest;
    mem["psram_free"]=m.psramFree;mem["psram_largest"]=m.psramLargest;
  }
}
}
#endif
