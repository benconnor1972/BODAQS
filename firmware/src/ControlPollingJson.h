#include "CpuOccupancyJson.h"
#pragma once
#include "ControlPollingDiagnostics.h"
#include "SparseCostJson.h"
#if defined(BODAQS_PACKED_EXCHANGE) && BODAQS_PACKED_EXCHANGE
#include "CanMasterManager.h"
#endif
#if BODAQS_CONTROL_POLL_DIAGNOSTICS
#include <ArduinoJson.h>
namespace ControlPollingJson {
template<class T,size_t N> inline void values(JsonObject row,const char* key,const T (&items)[N]){
  auto a=row[key].to<JsonArray>();for(auto value:items)a.add(value);
}
inline void append(JsonDocument& document,bool retired,uint64_t context){
  using namespace ControlPollingDiagnostics;
  CpuOccupancyJson::append(document,retired,context);
#if BODAQS_SPARSE_COST_PROBE
  SparseCostJson::append(document,retired && memory && memory->initialized,context,memory?memory->originUs:0);
#endif
#if defined(BODAQS_PACKED_EXCHANGE) && BODAQS_PACKED_EXCHANGE
  CanMasterManager::PackedDiagnostics packed;auto packedOut=document["packed_exchange"].to<JsonObject>();
  const bool packedAvailable=retired && CanMasterManager::packedDiagnostics(packed) && packed.context==context;
  packedOut["version"]=1;packedOut["available"]=packedAvailable;
  if(packedAvailable){packedOut["context"]=context;packedOut["packets"]=packed.packets;packedOut["items"]=packed.items;
    packedOut["protocol_version"]=packed.protocol_version;
    packedOut["confirmation_scope"]=packed.protocol_version==3?"metadata_only":"all_objects";
    values(packedOut,"sample_ram_custody_units",packed.sample_custody);
    auto policy=packedOut["command_policy"].to<JsonObject>();policy["version"]=1;policy["batching"]=packed.progress_batch;
    policy["minimum_custody_units"]=2;policy["maximum_intentional_hold_us"]=4000;
    policy["coalesced_attempts"]=packed.coalesced_commands;policy["unchanged_cache_hits"]=packed.unchanged_commands;
    policy["observed_hold_max_us"]=packed.progress_hold_max_us;
    policy["scope"]="hold_from_first_pending_command_attempt;observed_includes_service_delay;metadata_and_not_running_flush";
    packedOut["rejected"]=packed.rejected;packedOut["owner_copies"]=packed.copies;
    packedOut["pending_ack_batch"]=packed.pending;packedOut["exhausted"]=packed.exhausted;
    const auto& u=packed.utilization;auto util=packedOut["utilization"].to<JsonObject>();util["version"]=1;
    util["scope"]="measurement_through_cleanup;spacing_includes_encoding_and_wait;credits_local_point_samples;repeats_same_cell_object_not_unique_loss";
    util["exchanges"]=u.exchanges;util["transferred"]=u.transferred;util["commands"]=u.commands;
    util["new_commands"]=u.new_commands;util["retries"]=u.retries;util["confirmations"]=u.confirmations;
    util["exchange_us"]=u.exchange_us;util["used_body_bytes"]=u.used_bytes;
    util["confirmation_total_us"]=u.confirmation_us;util["confirmation_max_us"]=u.confirmation_max_us;
    util["spacing_count"]=u.spacing_count;util["spacing_total_us"]=u.spacing_us;util["spacing_max_us"]=u.spacing_max_us;
    values(util,"reply_item_count_hist",u.reply_counts);values(util,"class_items",u.class_items);
    values(util,"class_payload_bytes",u.class_bytes);values(util,"repeat_items",u.repeat_items);
    values(util,"local_credit_hist",u.credit_hist);
    auto capacity=packedOut["ack_capacity"].to<JsonObject>();capacity["version"]=1;
    capacity["scope"]="batches_at_construction;backlog_at_packed_attempt_excludes_inflight;confirmation_attributed_to_batch_start_phase;phase_by_LoggingManager_isRunning";
    capacity["delay_edges_us"]="2000,4000,8000,12000,20000";
    auto phases=capacity["phases"].to<JsonArray>();unsigned phaseIndex=0;
    for(const char* name:{"startup","recording","cleanup"}){auto row=phases.add<JsonObject>();const auto& d=packed.ack_capacity[phaseIndex++];row["phase"]=name;
     row["full_batches_with_waiting"]=d.full_batches_with_waiting;row["nonempty_batches_with_waiting"]=d.nonempty_batches_with_waiting;values(row,"batch_size_hist",d.batches);row["observations"]=d.observations;values(row,"waiting_total_hist",d.backlog_hist);
     values(row,"waiting_sum_by_class",d.backlog_sum);values(row,"waiting_max_by_class",d.backlog_max);
     row["confirmations"]=d.confirmations;row["confirmation_total_us"]=d.delay_total_us;row["confirmation_max_us"]=d.delay_max_us;values(row,"confirmation_delay_hist",d.delay_hist);
    }}

#endif

  auto out=document["control_poll_timeline"].to<JsonObject>();out["version"]=1;
  const bool available=retired && memory && memory->initialized && acquisition && acquisition->context==context &&
      acquisition->originUs==memory->originUs;
  out["available"]=available;if(memory)memory->frozen=true;
  if(!available)return;
  out["context"]=context;out["origin_us"]=memory->originUs;
  out["bin_us"]=RecordingTimelineDiagnostics::binUs;out["capacity"]=capacity;
  out["acquisition_used"]=acquisition->used;out["memory_used"]=memory->used;
  out["acquisition_overflow_events"]=acquisition->overflow;out["memory_overflow_events"]=memory->overflow;
  out["scope"]="MOSI_attempts_not_response_pairs_memory_point_samples_not_CPU_or_causality";
#if BODAQS_ACQUISITION_PROFILE
  out["profile_version"]=BODAQS_TRANSPORT_PROFILE?2:1;
  out["profile_scope"]="start_bin_wall_time_nested_not_CPU_core_at_service_entry";
  auto stages=out["profile_stages"].to<JsonArray>();
  for(const char* name:{"service","selection","transport","consumers","encode","spi_wait","spi_prepare","spi_transfer","spi_finish","decode","burst","sleep"})stages.add(name);
#if BODAQS_TRANSPORT_PROFILE
  for(const char* name:{"transport_request","transport_exchange","transport_response","fragment_accept"})stages.add(name);
#endif
#endif
  auto rows=out["bins"].to<JsonArray>();
  const uint32_t used=acquisition->used>memory->used?acquisition->used:memory->used;
  for(uint32_t i=0;i<used;++i){
    auto row=rows.add<JsonObject>();row["index"]=i;const auto& b=acquisition->bins[i];
    values(row,"targets",b.targets);values(row,"reasons",b.reasons);values(row,"fetches",b.fetches);
    values(row,"pending_fetches",b.pendingFetches);values(row,"age_sum_ms",b.ageSumMs);values(row,"age_max_ms",b.ageMaxMs);
    values(row,"first_operation",b.firstOperation);values(row,"last_operation",b.lastOperation);
    values(row,"begins",b.begins);values(row,"matched",b.matched);values(row,"timeouts",b.timeouts);
    values(row,"matched_age_max_ms",b.matchedAgeMaxMs);
    auto op=row["last_opcode"].to<JsonArray>();auto page=row["last_page"].to<JsonArray>();
    for(unsigned n=0;n<4;++n){op.add(b.lastOpcode[n]);page.add(b.lastPage[n]);}
#if BODAQS_ACQUISITION_PROFILE
    auto profile=row["profile"].to<JsonObject>();
    const auto& current=profileAt(i);
    values(profile,"total_us",current.totalUs);values(profile,"max_us",current.maxUs);
    values(profile,"calls",current.calls);values(profile,"cores",current.cores);
    values(profile,"reclaimed",current.reclaimed);profile["legacy_blocked_window_open"]=current.legacyBlockedWindowOpen;
#endif
    const auto& m=memory->bins[i];auto mem=row["memory"].to<JsonObject>();
    mem["samples"]=m.samples;mem["elapsed_us"]=m.elapsedUs;
    mem["internal_free"]=m.internalFree;mem["internal_largest"]=m.internalLargest;
    mem["psram_free"]=m.psramFree;mem["psram_largest"]=m.psramLargest;
  }
}
}
#endif

