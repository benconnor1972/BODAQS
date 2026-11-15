#pragma once
#include "RecordingTimelineDiagnostics.h"
#if BODAQS_STORAGE_TIMELINE
#include <ArduinoJson.h>
namespace RecordingTimelineJson {
// Storage owner, after matching acquisition retirement; no live owner-bank reads.
inline void append(JsonDocument& document,bool producerRetired,uint64_t context) {
  using namespace RecordingTimelineDiagnostics;
  auto out=document["recording_timeline"].to<JsonObject>();out["version"]=1;
  const bool available=producerRetired && storage.initialized &&
      acquisition.context==context && acquisition.originUs==storage.originUs;
  out["available"]=available;
  storage.frozen=true; // Exclude this summary's own serialization and file writes.
  if(!available)return;
  out["context"]=context;out["origin_us"]=storage.originUs;
  out["bin_us"]=binUs;out["capacity"]=capacity;
  out["storage_used"]=storage.used;out["acquisition_used"]=acquisition.used;
  out["storage_last_elapsed_us"]=uint32_t(storage.lastEventUs-storage.originUs);
  out["acquisition_last_elapsed_us"]=uint32_t(acquisition.lastServiceUs-acquisition.originUs);
  out["storage_overflow_events"]=storage.overflow;out["acquisition_overflow_events"]=acquisition.overflow;
  out["scope"]="whole_operations_at_start_bin_service_gaps_at_end_observations_not_cpu_time_or_causality";
  auto rows=out["bins"].to<JsonArray>();
  const uint32_t used=storage.used>acquisition.used?storage.used:acquisition.used;
  for(uint32_t i=0;i<used;++i) {
    auto row=rows.add<JsonObject>();row["index"]=i;
    const auto& s=storage.bins[i];auto sd=row["storage"].to<JsonObject>();
    sd["writes"]=s.writes;sd["bytes"]=s.bytes;sd["write_us"]=s.writeUs;sd["write_max_us"]=s.writeMaxUs;sd["slow_writes"]=s.slowWrites;
    sd["flushes"]=s.flushes;sd["flush_us"]=s.flushUs;sd["flush_max_us"]=s.flushMaxUs;
    sd["service_calls"]=s.serviceCalls;sd["service_us"]=s.serviceUs;sd["non_io_service_us"]=s.nonIoServiceUs;
    sd["service_max_us"]=s.serviceMaxUs;sd["primary_peak"]=s.primaryPeak;sd["service_gap_max_us"]=s.serviceGapMaxUs;
    sd["service_time_invalid"]=s.serviceTimeInvalid;
    const auto& a=acquisition.bins[i];auto acq=row["acquisition"].to<JsonObject>();
    acq["services"]=a.services;acq["service_gap_max_us"]=a.serviceGapMaxUs;acq["gaps_over_10ms"]=a.gapsOver10ms;
    acq["sample_calls"]=a.sampleCalls;acq["sample_waits"]=a.sampleWaits;
    acq["evidence_calls"]=a.evidenceCalls;acq["evidence_waits"]=a.evidenceWaits;
    auto sp=acq["sample_peak"].to<JsonArray>();auto ep=acq["evidence_peak"].to<JsonArray>();
    auto sl=acq["source_loss_reports"].to<JsonArray>();auto el=acq["evidence_loss_reports"].to<JsonArray>();
    for(unsigned n=0;n<4;++n){sp.add(a.samplePeak[n]);ep.add(a.evidencePeak[n]);sl.add(a.sourceLossReports[n]);el.add(a.evidenceLossReports[n]);}
  }
}
}
#endif
