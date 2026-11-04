#include "RemoteImuStream.h"
#include <cstdio>
#include <cstring>
#include <algorithm>
#include <cmath>
#include <new>
namespace {
uint32_t u32(const uint8_t* p) { return BdqV2Format::getU32(p); }
uint16_t u16(const uint8_t* p) { return BdqV2Format::getU16(p); }
void put(uint8_t* p,uint32_t v) { BdqV2Format::putU32(p,v); }
const BdqV2CatalogStatusFlag flags[]={ {"discontinuity_before",1},{"producer_drop_before",2},{"source_recovery_before",4},{"timing_degraded",8},{"native_tick_estimated",16} };
const BdqV2CatalogChannel sampleChannels[]={
 {"sequence","sequence","count","uint32",0,"diagnostic"},
 {"native_tick","time","tick","uint32",4,"time"},
 {"status_flags","flags","bitmask","uint16",8,"diagnostic"},
 {"source_segment_id","source_segment","count","uint32",12,"diagnostic"},
 {"ax","acceleration","count","int16",16,"signal","x","sensor","accel"},
 {"ay","acceleration","count","int16",18,"signal","y","sensor","accel"},
 {"az","acceleration","count","int16",20,"signal","z","sensor","accel"},
 {"gx","angular_velocity","count","int16",22,"signal","x","sensor","gyro"},
 {"gy","angular_velocity","count","int16",24,"signal","y","sensor","gyro"},
 {"gz","angular_velocity","count","int16",26,"signal","z","sensor","gyro"}
};
const BdqV2CatalogChannel evidenceChannels[]={
 {"sequence","sequence","count","uint32",0,"diagnostic"},
 {"native_tick","native_tick","count","uint32",4,"diagnostic"},
 {"status_flags","status_flags","count","uint16",8,"diagnostic"},
 {"kind","kind","count","uint8",12,"diagnostic"},
 {"endpoint","endpoint","count","uint8",13,"diagnostic"},
 {"stream_epoch","stream_epoch","count","uint8",14,"diagnostic"},
 {"validity_mask","validity_mask","count","uint32",16,"diagnostic"},
 {"source_segment_id","source_segment_id","count","uint32",20,"diagnostic"},
 {"related_sequence","related_sequence","count","uint32",24,"diagnostic"},
 {"node_boot","node_boot","count","uint32",28,"diagnostic"},
 {"sensor_clock_epoch","sensor_clock_epoch","count","uint32",32,"diagnostic"},
 {"node_clock_epoch","node_clock_epoch","count","uint32",36,"diagnostic"},
 {"master_clock_epoch","master_clock_epoch","count","uint32",40,"diagnostic"},
 {"model_id","model_id","count","uint32",44,"diagnostic"},
 {"node_evidence_ordinal","node_evidence_ordinal","count","uint32",48,"diagnostic"},
 {"raw_sensor_timestamp","raw_sensor_timestamp","count","uint32",52,"diagnostic"},
 {"drdy_node_tick","drdy_node_tick","count","uint32",56,"diagnostic"},
 {"capture_ordinal","capture_ordinal","count","uint32",60,"diagnostic"},
 {"sync_sequence","sync_sequence","count","uint32",64,"diagnostic"},
 {"node_sync_tick","node_sync_tick","count","uint32",68,"diagnostic"},
 {"master_sync_tick","master_sync_tick","count","uint32",72,"diagnostic"},
 {"master_receive_tick","master_receive_tick","count","uint32",76,"diagnostic"},
 {"master_receive_ordinal_low","master_receive_ordinal_low","count","uint32",80,"diagnostic"},
 {"fifo_accel_tag","fifo_accel_tag","count","uint8",84,"diagnostic"},
 {"fifo_gyro_tag","fifo_gyro_tag","count","uint8",85,"diagnostic"},
 {"fifo_timestamp_tag","fifo_timestamp_tag","count","uint8",86,"diagnostic"},
 {"association_flags","association_flags","count","uint8",87,"diagnostic"},
 {"anchor_sequence","anchor_sequence","count","uint32",88,"diagnostic"},
 {"anchor_node_tick","anchor_node_tick","count","uint32",92,"diagnostic"},
 {"step_numerator","step_numerator","count","uint32",96,"diagnostic"},
 {"step_denominator","step_denominator","count","uint32",100,"diagnostic"},
 {"uncertainty_us","uncertainty_us","count","uint32",104,"diagnostic"},
 {"maximum_sample_span","maximum_sample_span","count","uint32",108,"diagnostic"},
 {"maximum_duration_us","maximum_duration_us","count","uint32",112,"diagnostic"},
 {"fifo_slot_ordinal","fifo_slot_ordinal","count","uint32",116,"diagnostic"},
 {"logger_lower_low","logger_lower_low","count","uint32",120,"diagnostic"},
 {"logger_lower_high","logger_lower_high","count","uint32",124,"diagnostic"},
 {"logger_upper_low","logger_upper_low","count","uint32",128,"diagnostic"},
 {"logger_upper_high","logger_upper_high","count","uint32",132,"diagnostic"},
 {"bridge_master_tick","bridge_master_tick","count","uint32",136,"diagnostic"},
 {"bridge_method","bridge_method","count","uint16",140,"diagnostic"},
 {"boundary_reason","boundary_reason","count","uint16",142,"diagnostic"},
 {"bridge_token","bridge_token","count","uint32",144,"diagnostic"},
 {"source_loss_delta","source_loss_delta","count","uint32",148,"diagnostic"},
 {"evidence_loss_delta","evidence_loss_delta","count","uint32",152,"diagnostic"},
 {"capture_loss_delta","capture_loss_delta","count","uint32",156,"diagnostic"},
 {"first_affected","first_affected","count","uint32",160,"diagnostic"},
 {"last_affected","last_affected","count","uint32",164,"diagnostic"},
 {"loss_stage","loss_stage","count","uint8",168,"diagnostic"},
 {"count_validity","count_validity","count","uint16",170,"diagnostic"},
 {"first_input_ordinal","first_input_ordinal","count","uint32",172,"diagnostic"},
 {"last_input_ordinal","last_input_ordinal","count","uint32",176,"diagnostic"},
 {"clock_bound_flags","clock_bound_flags","count","uint32",180,"diagnostic"},
 {"original_message_type","original_message_type","count","uint8",184,"diagnostic"},
 {"original_message_version","original_message_version","count","uint8",185,"diagnostic"},
 {"original_message_length","original_message_length","count","uint8",186,"diagnostic"},
 {"master_receive_ordinal_high","master_receive_ordinal_high","count","uint32",188,"diagnostic"},
 {"boundary_node_tick","boundary_node_tick","count","uint32",192,"diagnostic"},
 {"recovery_elapsed_us","recovery_elapsed_us","count","uint32",196,"diagnostic"},
 {"boundary_event_kind","boundary_event_kind","count","uint8",200,"diagnostic"},
 {"snapshot_presence","snapshot_presence","count","uint8",201,"diagnostic"},
 {"model_kind","model_kind","count","uint8",202,"diagnostic"},
 {"snapshot_flags","snapshot_flags","count","uint16",204,"diagnostic"},
 {"model_flags","model_flags","count","uint16",206,"diagnostic"},
 {"boundary_validity_flags","boundary_validity_flags","count","uint16",208,"diagnostic"},
};
}
bool RemoteImuStream::configure(const RemoteImuBinding& b,uint16_t sample,uint16_t companion) {
  release(); if(!b.boot || b.node>3 || !sample || !companion || sample==companion) return false;
  if(!samples_.allocate(8192) || !evidence_.allocate(224,512)) {release();return false;}
  provenance_=static_cast<char*>(DynamicSpscQueueDetail::allocateBytes(3072));
  models_=static_cast<Model*>(DynamicSpscQueueDetail::allocateBytes(32*sizeof(Model)));
  anchors_=static_cast<Anchor*>(DynamicSpscQueueDetail::allocateBytes(32*sizeof(Anchor)));
  if(!provenance_ || !models_ || !anchors_) {release();return false;}
  for(unsigned i=0;i<32;++i) {new(models_+i) Model{};new(anchors_+i) Anchor{};}
  binding_=b;sampleId_=sample;evidenceId_=companion;
  char raw[385];for(size_t i=0;i<192;++i) std::snprintf(raw+2*i,3,"%02x",b.effective[i]);
  const bool scalingKnown=(u32(b.effective+12)&16u) && !(u32(b.effective+16)&16u) &&
    u32(b.effective+76) && u32(b.effective+84);
  const uint64_t accelScale=scalingKnown?uint64_t(u32(b.effective+72))*1000000/u32(b.effective+76):0;
  const uint64_t gyroScale=scalingKnown?uint64_t(u32(b.effective+80))*1000000/u32(b.effective+84):0;
  char mount[768];
  std::snprintf(mount,sizeof mount,"\"orientation_status\":\"unset\"");
  if(b.orientationValid) {
    const double w=b.mountingQuaternion[0],x=b.mountingQuaternion[1],y=b.mountingQuaternion[2],z=b.mountingQuaternion[3];
    const double norm=w*w+x*x+y*y+z*z;
    if(!std::isfinite(norm) || std::fabs(norm-1)>0.001) {release();return false;}
    std::snprintf(mount,sizeof mount,
      "\"orientation_status\":\"accepted\",\"saved_mount_quaternion\":[%.12g,%.12g,%.12g,%.12g],"
      "\"mount_transform\":{\"from\":\"sensor_native\",\"to\":\"body_local\",\"representation\":\"rotation_matrix\","
      "\"matrix\":[[%.12g,%.12g,%.12g],[%.12g,%.12g,%.12g],[%.12g,%.12g,%.12g]]}",
      w,x,y,z,1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w),
      2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w),
      2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y));
  }
  const int provenanceLength=std::snprintf(provenance_,3072,
    "\"provider_uid\":\"%llu\",\"node_address\":%u,\"node_boot\":%lu,\"master_boot\":\"%llu\",\"master_uid\":\"%llu\","
    "\"recording_id\":\"%llu\",\"control_session\":\"%llu\",\"measurement_context\":\"%llu\","
    "\"desired_generation\":\"%llu\",\"applied_revision\":\"%llu\",\"effective_descriptor_hex\":\"%s\","
    "\"known_mask\":%lu,\"historical_mask\":%lu,\"engine_power_bits\":%u,"
    "\"verification_phase\":\"stopped_configuration_at_admission\","
    "\"runtime_proof\":\"separate_acquisition_state\",%s,"
    "\"related_sample_stream_id\":%u,\"raw_axis_scaling\":{\"valid\":%s,\"accel_ug_per_count\":%llu,\"gyro_udps_per_count\":%llu},"
    "\"nominal_sensitivities\":{\"accel_g_numerator\":%lu,\"accel_g_denominator\":%lu,"
    "\"gyro_dps_numerator\":%lu,\"gyro_dps_denominator\":%lu},"
    "\"sensor_clock_id\":\"can%u_sensor_boot_%lu\",\"master_clock_id\":\"master_boot_%llu_native\","
    "\"logger_clock_id\":\"logger_monotonic_creation\",\"master_clock_epoch_scope\":\"one_per_boot_fail_closed_on_discontinuity\",\"master_timestamp_nominal_hz\":1000000,\"master_timestamp_modulus\":4294967296,\"physical_timing_bounds\":\"unknown_pending_qualification\",\"node_sync_capture_flags\":{\"0\":\"raw_capture_sequence_unknown\",\"1\":\"sequence_association_proven\"},\"bridge_methods\":{\"1\":\"complete_causal_bracket\",\"2\":\"expired_token_only_no_master_observation\"},"
    "\"sensor_timestamp_nominal_hz\":40000,\"sensor_timestamp_modulus\":4294967296,"
    "\"tick_semantics\":\"modelled_acceleration_output_ready\",\"inter_node_alignment\":\"unknown\","
    "\"uncertainty_validity\":\"validity_mask bit13\",\"snapshot_flag_semantics\":\"acquisition_contract_5.1\","
    "\"clock_bound_flags_semantics\":\"bits0..7 original reception flags; bit0 receive tick unknown\",\"validity_mask_semantics\":\"acquisition_contract_6.1\",\"tag_decoding\":\"LSM6DSO32X FIFO_DATA_OUT_TAG\","
    "\"companion_prefix_semantics\":\"logger_creation_observation_not_sample_time\"",
    (unsigned long long)b.uid,b.node,(unsigned long)b.boot,(unsigned long long)b.masterBoot,(unsigned long long)b.masterUid,
    (unsigned long long)b.recording,(unsigned long long)b.session,(unsigned long long)b.context,
    (unsigned long long)BdqV2Format::getU64(b.effective+24),(unsigned long long)BdqV2Format::getU64(b.effective+32),raw,
    (unsigned long)u32(b.effective+12),(unsigned long)u32(b.effective+16),b.effective[5],mount,sample,
    scalingKnown?"true":"false",(unsigned long long)accelScale,(unsigned long long)gyroScale,
    (unsigned long)u32(b.effective+72),(unsigned long)u32(b.effective+76),
    (unsigned long)u32(b.effective+80),(unsigned long)u32(b.effective+84),
    b.node,(unsigned long)b.boot,(unsigned long long)b.masterBoot);
  if(provenanceLength<0 || size_t(provenanceLength)>=3072) {release();return false;}
  return true;
}
size_t RemoteImuStream::allocatedBufferBytes() {
 return 8192*sizeof(Sample)+512*224+3072+32*sizeof(Model)+32*sizeof(Anchor);
}
void RemoteImuStream::release() {
  samples_.release();evidence_.release();sampleId_=evidenceId_=0;
  segment_=nextSequence_=stagedEvidence_=modelCount_=epoch_=anchorCount_=0;nextEvidence_=1;
  persistedEvidence_.store(0);haveSequence_=haveBoundary_=failed_=holding_=false;

  DynamicSpscQueueDetail::releaseBytes(provenance_);provenance_=nullptr;
  DynamicSpscQueueDetail::releaseBytes(models_);models_=nullptr;
  DynamicSpscQueueDetail::releaseBytes(anchors_);anchors_=nullptr;
  for(auto& l:losses_) l=Loss{};
  producerGap_=alignmentDegraded_=false;lossDependency_=0;
  std::memset(managementLoss_,0,sizeof managementLoss_);
  lastLossReport_=nextLossLane_=0;

}
BdqV2StreamSource RemoteImuStream::sampleSource() {
  BdqV2StreamSource s;s.streamId=sampleId_;s.recordSizeBytes=28;s.nativeTickModulus=uint64_t{1}<<32;
  s.context=this;s.pendingRecords=pendingSamples;s.pendingObservations=noObservations;s.popRecord=popSample;s.popObservation=noObservation;return s;
}
BdqV2StreamSource RemoteImuStream::evidenceSource() {
  auto s=sampleSource();s.streamId=evidenceId_;s.recordSizeBytes=224;s.pendingRecords=pendingEvidence;s.popRecord=popEvidence;s.chunkWritten=writtenEvidence;return s;
}
size_t RemoteImuStream::pendingSamples(const void* p) {
  auto& s=*const_cast<RemoteImuStream*>(static_cast<const RemoteImuStream*>(p));
  if(!s.holding_) s.holding_=s.samples_.pop(s.held_);
  if(!s.holding_ || s.held_.dependency>s.persistedEvidence_.load(std::memory_order_acquire)) return 0;
  return 1+s.samples_.size(); // each pop rechecks its own evidence dependency
}
size_t RemoteImuStream::pendingEvidence(const void* p) {return static_cast<const RemoteImuStream*>(p)->evidence_.size();}
bool RemoteImuStream::popSample(void* p,uint8_t* out,size_t capacity) {
  auto& s=*static_cast<RemoteImuStream*>(p);if(capacity<28 || !pendingSamples(p)) return false;
  std::memcpy(out,s.held_.bytes,28);s.holding_=false;return true;
}
bool RemoteImuStream::popEvidence(void* p,uint8_t* out,size_t capacity) {
  auto& s=*static_cast<RemoteImuStream*>(p);if(!s.evidence_.pop(out,capacity)) return false;
  s.stagedEvidence_=u32(out);return true;
}
void RemoteImuStream::writtenEvidence(void* p) {
  auto& s=*static_cast<RemoteImuStream*>(p);s.persistedEvidence_.store(s.stagedEvidence_,std::memory_order_release);
}
BdqV2StreamDescriptor RemoteImuStream::descriptor(bool ev) {
  BdqV2StreamDescriptor d;d.source=ev?evidenceSource():sampleSource();
  std::snprintf(d.streamKey,sizeof d.streamKey,"can%u_%s",binding_.node,ev?"timing":"imu6");
  std::snprintf(d.sensorId,sizeof d.sensorId,"%s",binding_.sensorId);
  std::snprintf(d.transport,sizeof d.transport,"can_fd");
  if(ev) std::snprintf(d.streamKind,sizeof d.streamKind,"intermittent");
  std::snprintf(d.clockId,sizeof d.clockId,ev?"logger_monotonic_creation":"can%u_boot%lu_native",binding_.node,(unsigned long)binding_.boot);
  std::snprintf(d.requestedProfile,sizeof d.requestedProfile,"imu6_3333_32g_2000dps_v1");
  std::snprintf(d.payloadSchema,sizeof d.payloadSchema,ev?"bodaqs.can_timing_evidence.v1":"bodaqs.can_imu6.v1");
  std::snprintf(d.domain,sizeof d.domain,"%s",binding_.domain);
  std::snprintf(d.end,sizeof d.end,"%s",binding_.end);
  std::snprintf(d.mountPoint,sizeof d.mountPoint,"%s",binding_.mountPoint);
  std::snprintf(d.calibrationRef,sizeof d.calibrationRef,"%s",binding_.calibrationRef);
  d.nominalSampleRateNumeratorHz=ev?50:3333;d.effectiveAccelRateHz=d.effectiveGyroRateHz=3333;
  d.channels=ev?evidenceChannels:sampleChannels;d.channelCount=ev?sizeof evidenceChannels/sizeof *evidenceChannels:sizeof sampleChannels/sizeof *sampleChannels;
  d.statusFlags=flags;d.statusFlagCount=sizeof flags/sizeof *flags;d.acquisitionDetailsJson=provenance_;return d;
}
RemoteImuStream::Acceptance RemoteImuStream::accept(uint16_t id,const uint8_t* p,size_t n,uint32_t tick,uint64_t order,uint32_t logger,uint8_t receptionFlags) {
  if(failed_ || !sampleId_ || !p) return Invalid;
  if(id==0x100+8*binding_.node) return samples(p,n,logger);
  if(id!=0x90+binding_.node || n<8 || p[0]!=1 || p[2]!=1 || p[3] || p[7]) return Invalid;
  if(p[1]==0x22) {
    if(n!=32 || p[6]!=20 || p[8] || p[9]!=1 || u16(p+26) || u32(p+28)) return Invalid;
    for(uint8_t i=0;i<modelCount_;++i) {auto& m=models_[i];
      if(m.epoch==p[10] && m.anchor==u32(p+12)) {
        if(m.tick==u32(p+16) && m.numerator==u32(p+20) && m.denominator==u16(p+24)) {m.anchored=true;return Accepted;}
        failed_=true;return Invalid;
      }
    }
    // Holding this immutable head would prevent a later matching model from
    // reaching the logger. Retain the canonical origin in bounded RAM instead.
    for(uint8_t i=0;i<anchorCount_;++i) {
      const auto& a=anchors_[i];
      if(a.epoch==p[10] && a.sequence==u32(p+12)) {
        if(a.tick==u32(p+16) && a.numerator==u32(p+20) && a.denominator==u16(p+24)) return Accepted;
        failed_=true;return Invalid;
      }
    }
    if(!u32(p+20) || !u16(p+24) || anchorCount_==32) {failed_=true;return Invalid;}
    auto& a=anchors_[anchorCount_++];a.epoch=p[10];a.sequence=u32(p+12);a.tick=u32(p+16);
    a.numerator=u32(p+20);a.denominator=u16(p+24);
    return Accepted;
  }
  if(p[1]==0x21) {
    if(n!=24 || p[6]!=16 || u16(p+22) || u32(p+16)!=binding_.boot ||
       u16(p+4)!=uint16_t(u32(p+8))) return Invalid;
    uint8_t out[224]={};put(out+4,logger);out[12]=3;out[14]=epoch_;
    put(out+16,(1u<<0)|(1u<<1)|(1u<<3)|(1u<<7)|((receptionFlags&1)?0:1u<<9)|(1u<<10)|(1u<<22));
    put(out+20,segment_);put(out+28,binding_.boot);put(out+36,1);put(out+40,1);
    put(out+64,u32(p+8));put(out+68,u32(p+12));put(out+76,(receptionFlags&1)?0:tick);put(out+180,receptionFlags);
    put(out+80,(uint32_t)order);put(out+188,(uint32_t)(order>>32));
    BdqV2Format::putU16(out+140,u16(p+20));out[184]=0x21;out[185]=1;out[186]=24;
    return pushShared(out);
  }
  if(n!=64 || p[6]!=56 || p[1]<0x23 || p[1]>0x25) return Invalid;
  if(u32(p+8)!=binding_.boot || p[12]) return Invalid;
  return evidence(p[1],p+8,tick,order,logger,false,receptionFlags);
}
RemoteImuStream::Acceptance RemoteImuStream::evidence(uint8_t type,const uint8_t* b,uint32_t tick,uint64_t order,uint32_t logger,bool local,uint8_t receptionFlags) {
  if(type==0x23 && evidence_.size()>=evidence_.capacity()-8) {
    return drop(1,1,0,logger)?Accepted:Invalid;
  }
  if(!flushLoss(logger)) return Invalid;
  if(evidence_.size()==evidence_.capacity() || nextEvidence_==UINT32_MAX) {failed_=true;return Invalid;}
  uint8_t out[224]={};put(out,nextEvidence_);put(out+4,logger);out[12]=type==0x23?1:type==0x24?2:b[6]==3?7:6;
  out[13]=b[4];out[14]=b[5];put(out+28,binding_.boot);put(out+76,(receptionFlags&1)?0:tick);put(out+180,receptionFlags);put(out+80,(uint32_t)order);put(out+188,(uint32_t)(order>>32));
  if(!local) {out[184]=type;out[185]=1;out[186]=64;}
  uint32_t valid=(1u<<0)|((receptionFlags&1)?0:1u<<9)|(1u<<10);
  if(type==0x25) {
    if(!local) put(out+48,u32(b+8));
    const uint16_t v=u16(b+46);if(v&~2047u || b[6]<1 || b[6]>8) return Invalid;
    if(b[6]==2) {
      if(segment_==UINT32_MAX) {failed_=true;return Invalid;}
      ++segment_;epoch_=b[5];haveBoundary_=true;haveSequence_=false;modelCount_=0;
    }
    if(!local && (!haveBoundary_ || b[5]!=epoch_)) return Invalid;
    if(v&1) {put(out+24,u32(b+20));valid|=1u<<4;}
    if(v&2) {put(out+160,u32(b+24));put(out+164,u32(b+28));valid|=1u<<19;}
    if(v&4) {put(out+148,u32(b+32));valid|=1u<<16;}
    if(v&8) {put(out+152,u32(b+40));valid|=1u<<17;}
    if(v&16) {put(out+156,u32(b+36));valid|=1u<<18;}
    if(v&32) {put(out+32,u32(b+12));put(out+36,u32(b+16));valid|=6;}
    if(v&64) put(out+192,u32(b+52));
    out[168]=b[7];BdqV2Format::putU16(out+170,v);BdqV2Format::putU16(out+142,u16(b+44));
    put(out+196,u32(b+48));out[200]=b[6];BdqV2Format::putU16(out+208,v);valid|=1u<<22;
  } else if(type==0x24) {
    if(!haveBoundary_ || b[5]!=epoch_ || !(u16(b+6)&1) || (u16(b+6)&~31u) || b[34]!=1 || b[35] || !u16(b+32) || !u32(b+8) || !u32(b+28) || !u32(b+36) || !u32(b+44)) return Invalid;
    if(u32(b+36)>500 || u32(b+44)>150000) return Invalid;
    for(uint8_t i=0;i<modelCount_;++i) {
      const auto& old=models_[i];
      if(old.id==u32(b+8) || old.anchor==u32(b+20)) {
        if(std::memcmp(old.canonical,b,56)==0) return Accepted;
        failed_=true;return Invalid;
      }
    }
    if(modelCount_==32) { // retire only decoded definitions; queued native records retain evidence serials
      if(!haveSequence_ || uint32_t(nextSequence_-models_[0].anchor)<models_[0].span) {
        failed_=true;return Invalid;
      }
      for(uint8_t i=1;i<modelCount_;++i) models_[i-1]=models_[i];
      --modelCount_;
    }
    auto& m=models_[modelCount_++];m=Model{};m.id=u32(b+8);m.epoch=b[5];m.flags=u16(b+6);m.nodeEpoch=u32(b+12);m.sensorEpoch=u32(b+16);m.anchor=u32(b+20);m.tick=u32(b+24);m.numerator=u32(b+28);m.denominator=u16(b+32);m.span=u32(b+36);m.duration=u32(b+44);m.dependency=nextEvidence_;
    std::memcpy(m.canonical,b,56);
    for(uint8_t i=0;i<anchorCount_;++i) {
      const auto& a=anchors_[i];
      if(a.epoch==m.epoch && a.sequence==m.anchor) {
        if(a.tick!=m.tick || a.numerator!=m.numerator || a.denominator!=m.denominator) {failed_=true;return Invalid;}
        m.anchored=true;
        for(uint8_t j=i+1;j<anchorCount_;++j) anchors_[j-1]=anchors_[j];
        --anchorCount_;break;
      }
    }
    put(out+44,m.id);put(out+32,m.sensorEpoch);put(out+36,m.nodeEpoch);put(out+24,m.anchor);put(out+88,m.anchor);put(out+92,m.tick);put(out+96,m.numerator);put(out+100,m.denominator);put(out+108,m.span);put(out+112,m.duration);
    if(m.flags&2) {put(out+104,u32(b+40));valid|=1u<<13;}
    if(m.flags&4) {put(out+172,u32(b+48));put(out+176,u32(b+52));valid|=1u<<20;}
    out[202]=b[34];BdqV2Format::putU16(out+206,m.flags);valid|=6|(1u<<4)|(1u<<12);
  } else {
    if(!haveBoundary_ || b[5]!=epoch_ || u16(b+6)&~511u) return Invalid;
    const uint8_t presence=b[51];const uint16_t association=u16(b+6);
    put(out+48,u32(b+8));put(out+32,u32(b+16));put(out+36,u32(b+20));valid|=6;
    if(presence&128) {put(out+24,u32(b+12));valid|=1u<<4;}
    if(presence&8) {put(out+52,u32(b+24));valid|=1u<<5;}
    if(presence&16) {put(out+56,u32(b+28));put(out+60,u32(b+32));valid|=1u<<6;}
    if(presence&32) {put(out+64,u32(b+36));put(out+68,u32(b+40));valid|=1u<<7;}
    if(association&16) put(out+44,u32(b+44));
    if(presence&7) {for(unsigned i=0;i<3;++i) if(presence&(1u<<i)) out[84+i]=b[48+i];valid|=1u<<11;}
    if(presence&64) {put(out+116,u32(b+52));valid|=1u<<21;}
    out[87]=(uint8_t)association;out[201]=presence;BdqV2Format::putU16(out+204,association);
  }
  put(out+20,segment_);put(out+16,valid);
  if(!evidence_.push(out,224)) {failed_=true;return Invalid;}
  ++nextEvidence_;
  if(local && u16(b+44)==31) failed_=true;
  return Accepted;
}
RemoteImuStream::Acceptance RemoteImuStream::samples(const uint8_t* p,size_t n,uint32_t logger) {
  if(n<16 || !haveBoundary_ || p[2]!=epoch_) return Invalid;
  const uint8_t count=p[3]&7;if(!count || count>5 || n<4+12u*count) return Invalid;
  for(size_t i=4+12u*count;i<n;++i) if(p[i]) return Invalid;
  uint32_t seq=haveSequence_?nextSequence_:0;
  const uint16_t delta=(uint16_t)(u16(p)-(uint16_t)seq);if(delta>=32768) return Invalid;
  seq+=delta;
  Model* selected=nullptr;
  for(uint8_t i=0;i<modelCount_;++i) {auto& m=models_[i];
    const uint32_t span=seq-m.anchor;
    if(m.anchored && m.epoch==epoch_ && span<0x80000000u && span+count<=m.span &&
       (uint64_t)(span+count-1)*m.numerator/m.denominator<=m.duration) selected=&m;
  }
  // The master preserves one ordered selected data/evidence head. A missing
  // definition cannot be fetched behind this pinned dependent head: fail the
  // source explicitly instead of waiting forever or inventing a native tick.
  if(!selected) {failed_=true;return Invalid;}
  if(!flushLoss(logger)) return Invalid;
  if(samples_.capacity()-samples_.size()<count || losses_[0].source) {
    nextSequence_=seq+count;haveSequence_=true;
    return drop(0,count,seq,logger)?Accepted:Invalid;
  }
  auto& m=*selected;
  for(uint8_t i=0;i<count;++i) {
    Sample out={};put(out.bytes,seq+i);put(out.bytes+4,m.tick+(uint32_t)((uint64_t)(seq+i-m.anchor)*m.numerator/m.denominator));
    uint16_t status=BdqV2Format::NativeTickEstimated;
    if(!(m.flags&2) || (p[3]&64) || alignmentDegraded_) status|=BdqV2Format::TimingDegraded;
    if(i==0 && (!haveSequence_ || delta || (p[3]&8))) status|=BdqV2Format::DiscontinuityBefore;
    if(i==0 && !haveSequence_ && (m.flags&16)) status|=BdqV2Format::SourceRecoveryBefore;
    if(i==0 && (p[3]&48)) status|=BdqV2Format::ProducerQueueDropBefore;
    if(i==0 && producerGap_) status|=BdqV2Format::DiscontinuityBefore|BdqV2Format::ProducerQueueDropBefore;
    BdqV2Format::putU16(out.bytes+8,status);put(out.bytes+12,segment_);std::memcpy(out.bytes+16,p+4+12*i,12);
    out.dependency=std::max(m.dependency,lossDependency_);if(!samples_.push(out)) return Invalid;
  }
  producerGap_=false;
  nextSequence_=seq+count;haveSequence_=true;return Accepted;
}

RemoteImuStream::Acceptance RemoteImuStream::pushShared(uint8_t out[224]) {
  if(failed_ || !sampleId_ || nextEvidence_==UINT32_MAX) return Invalid;
  if(evidence_.size()>=evidence_.capacity()-8) return drop(1,1,0,u32(out+4))?Accepted:Invalid;
  if(!flushLoss(u32(out+4))) return Invalid;
  put(out,nextEvidence_);
  if(!evidence_.push(out,224)) return Blocked;
  ++nextEvidence_;return Accepted;
}
bool RemoteImuStream::drop(unsigned lane,uint32_t count,uint32_t first,uint32_t logger) {
  auto& l=losses_[lane];uint32_t& total=lane?l.evidence:l.source;
  if(UINT32_MAX-total<count) {failed_=true;return false;}
  if(!lane && !total) l.first=first;
  total+=count;if(!lane) {l.last=first+count-1;producerGap_=true;} else alignmentDegraded_=true;
  return flushLoss(logger);
}
bool RemoteImuStream::flushLoss(uint32_t logger) {
  if(uint32_t(logger-lastLossReport_)<100000) return true;
  for(unsigned turn=0;turn<2;++turn) {
    const unsigned lane=(nextLossLane_+turn)%2;
    auto& l=losses_[lane];
    if(!l.source && !l.evidence) continue;
    if(evidence_.size()==evidence_.capacity() || nextEvidence_==UINT32_MAX) {failed_=true;return false;}
    uint8_t out[224]={};put(out,nextEvidence_);put(out+4,logger);out[12]=7;out[14]=epoch_;
    put(out+28,binding_.boot);put(out+20,segment_);out[168]=lane?9:8;out[200]=3;
    const uint32_t valid=(1u<<0)|(1u<<22)|(lane?(1u<<17):((1u<<16)|(1u<<19)));
    put(out+16,valid);put(out+148,l.source);put(out+152,l.evidence);
    if(!lane) {put(out+160,l.first);put(out+164,l.last);}
    BdqV2Format::putU16(out+170,lane?8:6);BdqV2Format::putU16(out+208,lane?8:6);
    if(!evidence_.push(out,224)) {failed_=true;return false;}
    lossDependency_=nextEvidence_++;l.source=l.evidence=0;lastLossReport_=logger;
    nextLossLane_=(lane+1)%2;return true;
  }
  return true;
}
bool RemoteImuStream::finish(uint32_t logger) {
  if(!flushLoss(logger)) return false;
  return !losses_[0].source && !losses_[1].evidence;
}
RemoteImuStream::Acceptance RemoteImuStream::acceptSharedSync(uint32_t sequence,uint32_t tick,uint32_t epoch,uint32_t logger) {
  if(!epoch) return Invalid;
  uint8_t out[224]={};put(out+4,logger);out[12]=4;
  put(out+16,(1u<<3)|(1u<<8)|(1u<<22));put(out+40,epoch);put(out+64,sequence);put(out+72,tick);
  return pushShared(out);
}
RemoteImuStream::Acceptance RemoteImuStream::acceptBridge(uint32_t token,uint32_t tick,uint32_t epoch,uint64_t lower,uint64_t upper,uint32_t logger) {
  if(!token || !epoch || upper<lower || upper-lower>=300000) return Invalid;
  uint8_t out[224]={};put(out+4,logger);out[12]=5;
  put(out+16,(1u<<3)|(1u<<14)|(1u<<15)|(1u<<22));put(out+40,epoch);
  BdqV2Format::putU64(out+120,lower);BdqV2Format::putU64(out+128,upper);
  put(out+136,tick);BdqV2Format::putU16(out+140,1);put(out+144,token);
  return pushShared(out);
}
RemoteImuStream::Acceptance RemoteImuStream::acceptLocalLoss(const uint8_t b[56],uint32_t tick,uint64_t order,uint32_t logger) {
  return evidence(0x25,b,tick,order,logger,true);
}
RemoteImuStream::Acceptance RemoteImuStream::acceptManagementLoss(uint8_t cls,uint8_t reason,uint16_t stage,uint32_t counter,uint32_t logger) {
  if(cls<1 || cls>2 || (stage!=5 && stage!=6) || (reason!=9 && reason!=14)) return Invalid;
  uint32_t& previous=managementLoss_[stage-5][cls-1];
  if(reason==9 && counter==previous) return Accepted;
  if(reason==9 && counter<previous) {failed_=true;return Invalid;}
  if(evidence_.size()==evidence_.capacity() || nextEvidence_==UINT32_MAX) {failed_=true;return Invalid;}
  uint8_t out[224]={};put(out,nextEvidence_);put(out+4,logger);out[12]=7;
  // ERROR counters are context/node/class scoped. Their wire representation
  // does not identify a source epoch, acquisition tick or CAN reception.
  put(out+28,binding_.boot);out[168]=(uint8_t)stage;out[200]=3;
  uint32_t valid=(1u<<0)|(1u<<22);
  if(reason==9) {
    put(out+(cls==1?148:152),counter-previous);valid|=1u<<(cls==1?16:17);
    BdqV2Format::putU16(out+170,cls==1?4:8);BdqV2Format::putU16(out+208,cls==1?4:8);
  } else BdqV2Format::putU16(out+142,31);
  put(out+16,valid);
  if(!evidence_.push(out,224)) {failed_=true;return Invalid;}
  previous=counter;++nextEvidence_;
  if(reason==14) failed_=true;
  return Accepted;
}

RemoteImuStream::Acceptance RemoteImuStream::acceptMissingBridge(uint32_t token,uint32_t logger) {
  if(!token) return Invalid;
  uint8_t out[224]={};put(out+4,logger);out[12]=5;
  // Method 2 records an expired token only. No epoch, M or logger interval is
  // present. It can never be composed as a bounded clock observation.
  put(out+16,(1u<<15)|(1u<<22));BdqV2Format::putU16(out+140,2);put(out+144,token);
  return pushShared(out);
}
