#pragma once
#include "RotaryCountStream.h"
#include "BdqV2Catalog.h"
#include "Sensor.h"
#include <stdio.h>

inline bool describeRotaryCountStream_(RotaryCountStream& stream,uint16_t id,
    const char* name,uint16_t rate,const char* provenance,BdqV2StreamDescriptor& out) {
  if(!id || !rate) return false;
  static const BdqV2CatalogChannel channels[]={
    {"sequence","sample_sequence","count","uint32",0,"diagnostic"},
    {"native_tick","sensor_time","us","uint32",4,"diagnostic"},
    {"status_flags","status","bitfield","uint16",8,"diagnostic"},
    {"raw_angle","absolute_angle","count","uint16",12,"signal"},
    {"angle_count","angle_register","count","uint16",14,"signal"},
    {"device_status","device_status","bitfield","uint16",16,"diagnostic"},
    {"agc","agc","count","uint8",18,"diagnostic"},
    {"auxiliary_validity","auxiliary_validity","bitfield","uint8",19,"diagnostic"},
    {"magnitude","magnitude","count","uint16",20,"diagnostic"},
    {"read_failures","read_failures","count","uint32",24,"diagnostic"},
    {"diagnostic_failures","diagnostic_failures","count","uint32",28,"diagnostic"}};
  static const BdqV2CatalogStatusFlag flags[]={
    {"discontinuity_before",1},{"producer_queue_drop_before",2},{"timing_degraded",8},{"read_failed",32}};
  out=BdqV2StreamDescriptor{};out.source=stream.source(id);
  snprintf(out.streamKey,sizeof out.streamKey,"%s_native",name);
  snprintf(out.sensorId,sizeof out.sensorId,"%s",name);
  snprintf(out.transport,sizeof out.transport,"i2c_direct");
  snprintf(out.clockId,sizeof out.clockId,"logger_monotonic");
  snprintf(out.clockRelation,sizeof out.clockRelation,"logger_monotonic");
  snprintf(out.requestedProfile,sizeof out.requestedProfile,"rotary_counts_v1");
  snprintf(out.payloadSchema,sizeof out.payloadSchema,"bodaqs.rotary_counts.v1");
  out.acquisitionDetailsJson=provenance;out.nominalSampleRateNumeratorHz=rate;
  out.channels=channels;out.channelCount=sizeof channels/sizeof channels[0];
  out.statusFlags=flags;out.statusFlagCount=sizeof flags/sizeof flags[0];
  return out.valid();
}
inline void fillRotaryDiagnostics_(const RotaryCountStream& stream,uint16_t rate,SensorRuntimeDiagnostics& out) {
  const auto stats=stream.stats();out.hasBdqV2Stream=true;
  out.bdqV2RecordsEnqueued=stats.recordsEnqueued;out.bdqV2RecordsDequeued=stats.recordsDequeued;
  out.bdqV2RecordsDropped=stats.recordsDropped;out.bdqV2RecordsRejected=stats.recordsRejected;
  out.bdqV2QueueCapacity=static_cast<uint16_t>(stream.capacity());
  out.bdqV2QueueHighWater=static_cast<uint16_t>(stats.recordQueueHighWater);
  out.bdqV2FinalQueueDepth=static_cast<uint16_t>(stream.pendingRecords());out.bdqV2NominalRateHz=rate;
}
