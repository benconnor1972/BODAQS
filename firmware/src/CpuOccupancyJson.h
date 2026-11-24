#pragma once
#include "CpuOccupancy.h"
#include <ArduinoJson.h>
namespace CpuOccupancyJson {
template<class T,size_t N> inline void values(JsonObject out,const char* key,const T (&v)[N]){auto a=out[key].to<JsonArray>();for(auto x:v)a.add(x);}
inline void append(JsonDocument& doc,bool retired,uint64_t context){
#if BODAQS_CPU_OCCUPANCY
 if(retired && !CpuOccupancy::snapshot(context))(void)CpuOccupancy::retire(context);
 const auto* s=retired?CpuOccupancy::snapshot(context):nullptr;auto out=doc["cpu_occupancy"].to<JsonObject>();
 out["version"]=1;out["available"]=s!=nullptr;
 out["scope"]="jittered_task_context_samples_not_exclusive_CPU_no_exact_ready_time";
 if(!s)return;
 out["context"]=s->context;out["origin_us"]=s->originUs;out["enabled"]=s->enabled;
 out["valid"]=s->valid;out["retired"]=s->retired;out["error"]=s->error;
 out["mhz_start"]=s->mhzStart;out["mhz_end"]=s->mhzEnd;out["bin_us"]=CpuOccupancy::binUs;
 auto tasks=out["tasks"].to<JsonArray>();for(auto name:{"acquisition","adc","sampler","storage","main","idle","other","calibration"})tasks.add(name);
 auto phases=out["phases"].to<JsonArray>();for(auto name:{"inactive","preparing","bus_wait","transfer","decode","consumers","sleep"})phases.add(name);
 auto cores=out["cores"].to<JsonArray>();
 for(const auto& c:s->cores){auto row=cores.add<JsonObject>();row["started_us"]=c.startedUs;row["used"]=c.used;row["overflow"]=c.overflow;
  row["callback_cycles_lower_bound"]=c.overheadCycles;row["max_callback_cycles_lower_bound"]=c.maxOverheadCycles;
  row["stopped_us"]=c.stoppedUs;row["unknown_us"]=c.unknownUs;row["tail_us"]=c.tailUs;
  row["ipc_stack_unused_min_bytes"]=c.ipcStackUnusedMin;
  row["interval_min_us"]=c.intervalMin;row["interval_max_us"]=c.intervalMax;values(row,"millisecond_phase_hist",c.phaseHist);
  values(row,"interval_hist_250us_capped7",c.intervalHist);
  auto bins=row["bins"].to<JsonArray>();for(unsigned i=0;i<c.used;++i){const auto& b=c.bins[i];auto bin=bins.add<JsonObject>();bin["index"]=i;
   bin["samples"]=b.samples;bin["gap_endpoints"]=b.gaps;bin["owner_remote_racy"]=b.ownerRemote;bin["unstable"]=b.unstable;
   values(bin,"tasks",b.tasks);values(bin,"owner_here",b.ownerHere);values(bin,"owner_absent",b.ownerAbsent);
  }
 }
#else
 (void)doc;(void)retired;(void)context;
#endif
}
}
