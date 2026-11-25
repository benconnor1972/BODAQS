#pragma once
#include "SparseCostProbe.h"
#if BODAQS_SPARSE_COST_PROBE
#include <ArduinoJson.h>
namespace SparseCostJson {
inline void metric(JsonArray array,const SparseCostProbe::Metric& m){auto row=array.add<JsonArray>();row.add(m.calls);row.add(m.totalUs);row.add(m.maxUs);}
template<class T,size_t N> inline void values(JsonObject row,const char* key,const T (&items)[N]){auto a=row[key].to<JsonArray>();for(auto v:items)a.add(v);}
inline void append(JsonDocument& document,bool retired,uint64_t context,uint32_t origin){
 using namespace SparseCostProbe;auto out=document["sparse_cost"].to<JsonObject>();
 const bool available=retired && state && state->context==context && state->originUs==origin && context;
 out["version"]=1;out["available"]=available;out["enabled"]=enabled;
 out["scope"]="sampled_service_start_bin_wall_time_including_preemption_not_exclusive_CPU_nested";
 out["selector"]="one_per64_services_rotating_position_stride17";out["sample_block"]=block;
 out["metric_fields"]="calls,total_us,max_us";
 out["packet_identity_scope"]="pre_receive_complete_or_below_base_not_unique_admission_or_loss";
 if(!available)return;
 out["context"]=context;out["origin_us"]=state->originUs;out["bin_us"]=RecordingTimelineDiagnostics::binUs;
 out["used"]=state->used;out["capacity"]=capacity;out["overflow_events"]=state->overflow;
 auto stages=out["stages"].to<JsonArray>();for(const char* n:{"service","consumers","control_accept"})stages.add(n);
 auto kinds=out["packet_kinds"].to<JsonArray>();for(const char* n:{"empty","unseen_small_sample","unseen_full_sample","known_or_late_sample","mixed","metadata","invalid_packed","legacy_or_transfer_failed","recovering"})kinds.add(n);
 auto parts=out["packet_parts"].to<JsonArray>();for(const char* n:{"envelope","codec","receiver","rest"})parts.add(n);
 auto rows=out["bins"].to<JsonArray>();
 for(unsigned i=0;i<state->used;++i){auto row=rows.add<JsonObject>();const auto& b=at(i);row["index"]=i;
  row["eligible_services"]=b.eligible;row["selected_services"]=b.selected;row["invalid_intervals"]=b.invalidIntervals;
  row["migrations"]=b.migrations;row["clock_changes"]=b.clockChanges;row["min_mhz"]=b.minMHz;row["max_mhz"]=b.maxMHz;
  values(row,"cores_in",b.coresIn);values(row,"cores_out",b.coresOut);
  auto a=row["stages"].to<JsonArray>();for(const auto& m:b.stages)metric(a,m);
  auto p=row["packets"].to<JsonArray>();for(const auto& kind:b.packets){auto k=p.add<JsonArray>();for(const auto& m:kind)metric(k,m);}
  auto c=row["consumer_by_class_result"].to<JsonArray>();for(const auto& cls:b.consumers){auto k=c.add<JsonArray>();for(const auto& m:cls)metric(k,m);}
  auto o=row["observer_by_class"].to<JsonArray>();for(const auto& m:b.observers)metric(o,m);
 }
}
}
#endif
