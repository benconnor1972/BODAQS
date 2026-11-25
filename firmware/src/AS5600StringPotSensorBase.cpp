#include "AS5600StringPotSensorBase.h"

#include <Arduino.h>
#include <math.h>
#include <string.h>

#include "ConfigManager.h"
#include "BdqV2Catalog.h"

namespace {

const char* linearUnit_(const char* configured) {
  return (configured && configured[0]) ? configured : "mm";
}

void copyField_(char* dst, size_t cap, const char* src) {
  if (!dst || cap == 0) return;
  if (!src) src = "";
  size_t n = strlen(src);
  if (n >= cap) n = cap - 1;
  memcpy(dst, src, n);
  dst[n] = '\0';
}

void writeColumnLabel_(const char* name, const char* units, char* out, size_t cap) {
  if (!out || cap < 2) return;
  out[0] = '\0';

  String s = name ? String(name) : String();
  if (units && units[0]) {
    s += " [";
    s += units;
    s += "]";
  }
  s.toCharArray(out, cap);
}

} // namespace

AS5600StringPotSensorBase::AS5600StringPotSensorBase(const BaseParams& p) {
  applyBaseParams(p);
}

void AS5600StringPotSensorBase::applyBaseParams(const BaseParams& p) {
  if (p.name && p.name[0]) {
    strncpy(m_name, p.name, sizeof(m_name) - 1);
    m_name[sizeof(m_name) - 1] = '\0';
  }

  m_countsPerTurn = (p.countsPerTurn >= 2) ? p.countsPerTurn : 4096;

  uint16_t defaultThreshold = uint16_t(m_countsPerTurn / 2);
  if (defaultThreshold == 0) defaultThreshold = 1;
  m_wrapThreshold = p.wrapThresholdCounts ? p.wrapThresholdCounts : defaultThreshold;
  if (m_wrapThreshold >= m_countsPerTurn) m_wrapThreshold = defaultThreshold;

  sensor_zero_count_ = p.sensorZeroCount;
  sensor_full_count_ = p.sensorFullCount;
  m_invert = (sensor_full_count_ < sensor_zero_count_);
  installed_zero_count_ = p.installedZeroCount;
  sensor_full_travel_mm_ = p.sensorFullTravelMm;
  m_installedRange = p.installedRange;
  m_assumeTurn0AtStart = p.assumeTurn0AtStart;
  m_includeRaw = p.includeRawColumn;

  copyField_(m_unitsLabel, sizeof(m_unitsLabel), "mm");
  Sensor::setOutputUnitsLabel(m_unitsLabel);

  copyField_(m_semanticEnd, sizeof(m_semanticEnd), p.semanticEnd);
  copyField_(m_primaryDomain, sizeof(m_primaryDomain), p.primaryDomain);
  copyField_(m_primaryQuantity, sizeof(m_primaryQuantity), p.primaryQuantity);
  copyField_(m_rawDomain, sizeof(m_rawDomain), p.primaryDomain);

  recomputeScale();
  resetTrackingState(m_assumeTurn0AtStart);
#if BODAQS_PRODUCTION_RECORDING
  (void)m_countStream.configure(countConfiguration_());
#endif
}

#if BODAQS_PRODUCTION_RECORDING
StringPotCountStream::Configuration AS5600StringPotSensorBase::countConfiguration_() const {
  StringPotCountStream::Configuration config;
  config.countsPerTurn=m_countsPerTurn;config.threshold=m_wrapThreshold;
  config.installedZero=installed_zero_count_;config.assumeTurnZero=m_assumeTurn0AtStart;
  config.analogSettling=hasAnalogWrapSettling();config.recordAuxiliary=hasCountAuxiliary();
  return config;
}
#endif

void AS5600StringPotSensorBase::resetTrackingState(bool assumeTurnZero) {
  m_trackingInit = false;
  m_wrapTracker.reset(0, 0, m_countsPerTurn);
}

void AS5600StringPotSensorBase::recomputeScale() {
  const int64_t span = int64_t(sensor_full_count_) - sensor_zero_count_;
  const int64_t spanAbs = (span >= 0) ? span : -span;
  if (sensor_full_travel_mm_ > 0.0f && spanAbs != 0) {
    counts_per_mm_ = double(spanAbs) / double(sensor_full_travel_mm_);
  } else {
    counts_per_mm_ = 0.0;
  }
}

void AS5600StringPotSensorBase::onLoggingStart() {
  resetTrackingState(m_assumeTurn0AtStart);
#if BODAQS_PRODUCTION_RECORDING
  m_sessionFrozen=m_countStream.active();
  if(!m_sessionFrozen) {
    (void)m_countStream.configure(countConfiguration_());m_idleSequence=0;
  }
#endif
}

void AS5600StringPotSensorBase::onLoggingStop() {
#if BODAQS_PRODUCTION_RECORDING
  m_countStream.stop();
#endif
}

void AS5600StringPotSensorBase::onLoggingFinalized() {
#if BODAQS_PRODUCTION_RECORDING
  (void)m_countStream.finalizeSession();
  m_sessionFrozen=false;
#endif
}

void AS5600StringPotSensorBase::loop() {
#if BODAQS_PRODUCTION_RECORDING
  if(m_sessionFrozen || m_muted) return;
  const uint32_t now=millis();
  if(m_nextIdleSampleMs && static_cast<int32_t>(now-m_nextIdleSampleMs)<0) return;
  m_nextIdleSampleMs=now+20;
  int32_t counts=0;const bool valid=readWrappedObservation(counts);
  publishCountObservation(counts,micros(),valid?0:0x20,m_idleSequence++);
#endif
}

bool AS5600StringPotSensorBase::prepareLoggingStart(const LoggerConfig&,uint16_t rate,char*,size_t) {
#if BODAQS_PRODUCTION_RECORDING
  m_nativeRateHz=countRecordingRateHz(rate);
  return m_nativeRateHz!=0;
#else
  (void)rate;return true;
#endif
}

bool AS5600StringPotSensorBase::startLoggingSession(char* error,size_t capacity) {
#if BODAQS_PRODUCTION_RECORDING
  if(!m_nativeRateHz || !m_countStream.configure(countConfiguration_()) || !m_countStream.begin()) {
    if(error && capacity) snprintf(error,capacity,"string-pot recording reservation failed");
    return false;
  }
  const int provenanceBytes=snprintf(m_countProvenance,sizeof m_countProvenance,
      "\"counts_per_turn\":%u,\"wrap_threshold_counts\":%u,\"assume_turn0_at_start\":%s,"
      "\"sequence_basis\":\"scheduled_acquisition_slots\","
      "\"unwrapped_interpretation\":\"firmware_estimate_not_proof_of_physical_turns\","
      "\"quality_flags\":{\"assumed_origin\":1,\"settling_held\":2,\"observation_gap\":4,"
      "\"uncertain\":8,\"invalid_input\":16,\"tracking_reset\":32,\"overflow\":64},"
      "\"auxiliary_validity\":{\"raw_current\":1,\"angle_current\":2,\"diagnostics_available\":4,\"raw_reused\":8}",
      unsigned(m_countsPerTurn),unsigned(m_wrapThreshold),m_assumeTurn0AtStart?"true":"false");
  if(provenanceBytes<0 || size_t(provenanceBytes)>=sizeof m_countProvenance) {
    m_countStream.stop();
    if(error && capacity) snprintf(error,capacity,"string-pot provenance overflow");
    return false;
  }
#else
  (void)error;(void)capacity;
#endif
  onLoggingStart();return true;
}

bool AS5600StringPotSensorBase::usesBdqV2NativeStream() const {
#if BODAQS_PRODUCTION_RECORDING
  return true;
#else
  return false;
#endif
}

size_t AS5600StringPotSensorBase::pendingLoggingRows() const {
#if BODAQS_PRODUCTION_RECORDING
  return m_countStream.pending();
#else
  return 0;
#endif
}

void AS5600StringPotSensorBase::appendCountRecordingDiagnostics(SensorRuntimeDiagnostics& out) const {
#if BODAQS_PRODUCTION_RECORDING
  const auto stats=m_countStream.stats();
  out.hasBdqV2Stream=true;
  out.bdqV2RecordsEnqueued=stats.recordsEnqueued;out.bdqV2RecordsDequeued=stats.recordsDequeued;
  out.bdqV2RecordsDropped=stats.recordsDropped;out.bdqV2RecordsRejected=stats.recordsRejected;
  out.bdqV2QueueCapacity=m_countStream.capacity();out.bdqV2QueueHighWater=stats.recordQueueHighWater;
  out.bdqV2FinalQueueDepth=m_countStream.pending();out.bdqV2NominalRateHz=m_nativeRateHz;
#else
  (void)out;
#endif
}

bool AS5600StringPotSensorBase::describeRuntimeDiagnostics(SensorRuntimeDiagnostics& out) const {
#if BODAQS_PRODUCTION_RECORDING
  out=SensorRuntimeDiagnostics{};out.present=true;
  copyField_(out.sensorName,sizeof out.sensorName,name());copyField_(out.kind,sizeof out.kind,"string_pot_counts");
  appendCountRecordingDiagnostics(out);return true;
#else
  (void)out;return false;
#endif
}

void AS5600StringPotSensorBase::publishAcquisitionCounts(int32_t counts,uint32_t tick,uint16_t status,uint32_t sequence) {
  publishCountObservation(counts,tick,status,sequence);
}

void AS5600StringPotSensorBase::publishCountObservation(int32_t counts,uint32_t tick,uint16_t status,uint32_t sequence) const {
#if BODAQS_PRODUCTION_RECORDING
  m_countStream.observe(counts,sequence,tick,status);
#else
  (void)counts;(void)tick;(void)status;(void)sequence;
#endif
}

void AS5600StringPotSensorBase::markCountObservationGap() {
#if BODAQS_PRODUCTION_RECORDING
  m_countStream.markObservationGap();
#endif
}
#if BODAQS_PRODUCTION_RECORDING
void AS5600StringPotSensorBase::publishI2CCountObservation(int32_t counts,uint32_t tick,uint16_t status,uint32_t sequence,const StringPotCountStream::Auxiliary& auxiliary) const {
  m_countStream.observe(counts,sequence,tick,status,auxiliary);
}
#endif

bool AS5600StringPotSensorBase::describeBdqV2Stream(uint16_t id,BdqV2StreamDescriptor& out) {
#if BODAQS_PRODUCTION_RECORDING
  if(m_muted || !id || !m_nativeRateHz) return false;
  static const BdqV2CatalogChannel channels[]={
    {"sequence","sample_sequence","count","uint32",0,"diagnostic"},
    {"native_tick","sensor_time","us","uint32",4,"diagnostic"},
    {"status_flags","status","bitfield","uint16",8,"diagnostic"},
    {"wrapped_count","wrapped_raw","count","uint16",12,"signal"},
    {"tracking_quality","tracking_quality","bitfield","uint16",14,"diagnostic"},
    {"unwrapped_count","unwrapped_raw","count","int32",16,"signal"},
    {"tracking_epoch","tracking_epoch","count","uint32",20,"diagnostic"},
    {"angle_count","angle","count","uint16",24,"signal"},
    {"device_status","device_status","bitfield","uint8",26,"diagnostic"},
    {"agc","agc","count","uint8",27,"diagnostic"},
    {"magnitude","magnitude","count","uint16",28,"diagnostic"},
    {"auxiliary_validity","auxiliary_validity","bitfield","uint16",30,"diagnostic"},
    {"read_failures","read_failures","count","uint32",32,"diagnostic"},
    {"diagnostic_failures","diagnostic_failures","count","uint32",36,"diagnostic"}};
  static const BdqV2CatalogStatusFlag flags[]={
    {"discontinuity_before",1},{"producer_queue_drop_before",2},{"timing_degraded",8},{"sensor_error",32}};
  out=BdqV2StreamDescriptor{};out.source=m_countStream.source(id);
  snprintf(out.streamKey,sizeof out.streamKey,"%s_counts",name());
  copyField_(out.sensorId,sizeof out.sensorId,name());
  copyField_(out.transport,sizeof out.transport,hasAnalogWrapSettling()?"local_adc":"i2c_direct");
  copyField_(out.clockId,sizeof out.clockId,"logger_monotonic");
  copyField_(out.clockRelation,sizeof out.clockRelation,"logger_monotonic");
  copyField_(out.requestedProfile,sizeof out.requestedProfile,"string_pot_counts_v1");
  copyField_(out.payloadSchema,sizeof out.payloadSchema,"bodaqs.string_pot_counts.v1");
  out.acquisitionDetailsJson=m_countProvenance;
  out.nominalSampleRateNumeratorHz=m_nativeRateHz;
  out.channels=channels;out.channelCount=hasCountAuxiliary()?sizeof channels/sizeof channels[0]:7;
  out.statusFlags=flags;out.statusFlagCount=sizeof flags/sizeof flags[0];
  return out.valid();
#else
  (void)id;(void)out;return false;
#endif
}

int AS5600StringPotSensorBase::normalizeWrapped_(int wrapped) const {
  const int turn = (m_countsPerTurn > 0) ? int(m_countsPerTurn) : 1;
  int out = wrapped % turn;
  if (out < 0) out += turn;
  return out;
}

int32_t AS5600StringPotSensorBase::initialUnwrappedFromWrapped_(int wrapped) const {
  wrapped = normalizeWrapped_(wrapped);

  if (!m_assumeTurn0AtStart) {
    return int32_t(wrapped);
  }

  const int32_t turn = (m_countsPerTurn > 0) ? int32_t(m_countsPerTurn) : 1;
  const int32_t zeroPhase = int32_t(normalizeWrapped_(int(installed_zero_count_)));
  int32_t relative = int32_t(wrapped) - zeroPhase;
  if (relative < 0) relative += turn;

  const int32_t zeroBase = installed_zero_count_ - zeroPhase;
  return zeroBase + relative;
}

int32_t AS5600StringPotSensorBase::updateUnwrappedFromWrapped_(int wrapped) const {
  wrapped = normalizeWrapped_(wrapped);
  if (!m_trackingInit) {
    m_trackingInit = true;
    const int32_t initial = initialUnwrappedFromWrapped_(wrapped);
    m_wrapTracker.reset(wrapped, initial, m_countsPerTurn);
    return initial;
  }

  return m_wrapTracker.update(wrapped, m_countsPerTurn, m_wrapThreshold,
                              hasAnalogWrapSettling());
}

AS5600StringPotSensorBase::SampleState AS5600StringPotSensorBase::captureSample_() const {
  SampleState s;
#if BODAQS_PRODUCTION_RECORDING
  StringPotCountStream::Sample observation;
  if(m_countStream.snapshot(observation)) {s.wrappedRaw=observation.wrapped;s.unwrappedRaw=observation.unwrapped;}
#else
  s.wrappedRaw = normalizeWrapped_(readWrappedCountsOnce());
  s.unwrappedRaw = updateUnwrappedFromWrapped_(s.wrappedRaw);
#endif
  return s;
}

float AS5600StringPotSensorBase::countsToMm_(int32_t counts) const {
  if (counts_per_mm_ <= 0.0) return 0.0f;
  double mm = (double(counts) - double(installed_zero_count_)) / counts_per_mm_;
  if (m_invert) mm = -mm;
  return float(mm);
}

uint8_t AS5600StringPotSensorBase::columnCount() const {
  uint8_t count = 1;
  if (m_mode == OutputMode::RAW) {
    ++count; // Preserve the existing linear secondary column in RAW mode.
  } else if (m_includeRaw) {
    ++count; // Existing wrapped raw column.
  }
  if (m_includeRaw) {
    ++count; // New unwrapped raw column.
  }
  return count;
}

bool AS5600StringPotSensorBase::isWrappedRawColumn_(uint8_t idx) const {
  return (m_mode == OutputMode::RAW && idx == 0) ||
         (m_mode != OutputMode::RAW && m_includeRaw && idx == 1);
}

bool AS5600StringPotSensorBase::isLinearSecondaryColumn_(uint8_t idx) const {
  return (m_mode == OutputMode::RAW && idx == 1);
}

bool AS5600StringPotSensorBase::isUnwrappedRawColumn_(uint8_t idx) const {
  if (!m_includeRaw) return false;
  return idx == 2;
}

void AS5600StringPotSensorBase::getColumnName(uint8_t idx, char* out, size_t cap) const {
  if (!out || cap < 2) return;
  out[0] = '\0';

  if (isWrappedRawColumn_(idx)) {
    String s = String(name()) + "_raw [counts]";
    s.toCharArray(out, cap);
    return;
  }

  if (isLinearSecondaryColumn_(idx)) {
    writeColumnLabel_(name(), linearUnit_(m_unitsLabel), out, cap);
    return;
  }

  if (isUnwrappedRawColumn_(idx)) {
    String s = String(name()) + "_unwrapped_raw [counts]";
    s.toCharArray(out, cap);
    return;
  }

  if (idx == 0) {
    writeColumnLabel_(name(), linearUnit_(m_outputUnitsLabel), out, cap);
  }
}

bool AS5600StringPotSensorBase::describeColumn(uint8_t idx, SensorColumnDescriptor& out) const {
  if (idx >= columnCount()) return false;
  if (!Sensor::describeColumn(idx, out)) return false;

  const bool wrappedRaw = isWrappedRawColumn_(idx);
  const bool unwrappedRaw = isUnwrappedRawColumn_(idx);
  const bool rawColumn = wrappedRaw || unwrappedRaw;
  const bool linearSecondary = isLinearSecondaryColumn_(idx);

  copyField_(out.sensorName, sizeof(out.sensorName), name());
  out.outputMode = m_mode;
  out.required = true;
  out.primary = (idx == 0);
  out.raw = rawColumn;
  out.calibrated = !rawColumn;
  out.transformed = (idx == 0 && (m_mode == OutputMode::POLY || m_mode == OutputMode::LUT));

  copyField_(out.end, sizeof(out.end), m_semanticEnd);
  copyField_(out.domain, sizeof(out.domain), rawColumn ? m_rawDomain : m_primaryDomain);
  if (!out.domain[0]) copyField_(out.domain, sizeof(out.domain), m_primaryDomain);

  if (rawColumn) {
    copyField_(out.quantity, sizeof(out.quantity), "raw");
    copyField_(out.unit, sizeof(out.unit), "counts");
    copyField_(out.source, sizeof(out.source),
               unwrappedRaw ? "unwrapped_raw_counts" : "wrapped_raw_counts");
    if (unwrappedRaw) {
      copyField_(out.transformChain, sizeof(out.transformChain), "unwrap");
    }
  } else {
    copyField_(out.quantity, sizeof(out.quantity), m_primaryQuantity);
    copyField_(out.unit, sizeof(out.unit), linearUnit_(m_outputUnitsLabel));
    copyField_(out.source, sizeof(out.source),
               linearSecondary ? "linearized" : (out.transformed ? "transformed" : "linear_calibrated"));
    copyField_(out.calibrationId, sizeof(out.calibrationId), "linear_unwrapped");
  }

  if (out.transformed && selectedTransformId().length()) {
    selectedTransformId().toCharArray(out.transformChain, sizeof(out.transformChain));
  }

  if (out.end[0] && out.domain[0] && out.quantity[0]) {
    snprintf(out.columnId, sizeof(out.columnId), unwrappedRaw ? "%s_%s_%s_unwrapped" : "%s_%s_%s",
             out.end, out.domain, out.quantity);
  } else if (out.quantity[0]) {
    snprintf(out.columnId, sizeof(out.columnId), unwrappedRaw ? "%s_%s_unwrapped" : "%s_%s",
             name(), out.quantity);
  }

  if (!out.quantity[0]) {
    copyField_(out.notes, sizeof(out.notes), "missing semantic quantity");
  } else if (!out.end[0] || !out.domain[0]) {
    copyField_(out.notes, sizeof(out.notes), "partial semantic metadata");
  } else {
    out.notes[0] = '\0';
  }

  return true;
}

bool AS5600StringPotSensorBase::describeSensorMetadata(SensorMetadataDescriptor& out) const {
  out = SensorMetadataDescriptor{};
  copyField_(out.sensorId, sizeof(out.sensorId), name());
  copyField_(out.name, sizeof(out.name), name());
  copyField_(out.type, sizeof(out.type), "as5600_string_pot");
  copyField_(out.domain, sizeof(out.domain), m_primaryDomain);
  copyField_(out.rawUnit, sizeof(out.rawUnit), "counts");
  copyField_(out.calibrationType, sizeof(out.calibrationType), "linear");
  copyField_(out.calibrationInputUnit, sizeof(out.calibrationInputUnit), "counts");
  copyField_(out.calibrationOutputUnit, sizeof(out.calibrationOutputUnit), linearUnit_(m_outputUnitsLabel));
  out.installedZeroCount = installed_zero_count_;
  out.sensorZeroCount = sensor_zero_count_;
  out.sensorFullCount = sensor_full_count_;
  out.sensorFullTravel = sensor_full_travel_mm_;
  out.invert = m_invert;
  out.hasCalibration = counts_per_mm_>0 && isfinite(counts_per_mm_);
  out.hasTracking = true;
  out.countsPerTurn = m_countsPerTurn;
  out.wrapThresholdCounts = m_wrapThreshold;
  out.assumeTurn0AtStart = m_assumeTurn0AtStart;
  return true;
}

void AS5600StringPotSensorBase::sampleValues(float* out, uint8_t max) {
  if (!out || max == 0 || m_muted) return;

  const SampleState sample = captureSample_();
  const float linearMm = countsToMm_(sample.unwrappedRaw);
  float primary = 0.0f;

  switch (m_mode) {
    case OutputMode::RAW:
      primary = float(sample.wrappedRaw);
      break;
    case OutputMode::LINEAR:
      primary = linearMm;
      break;
    case OutputMode::POLY:
    case OutputMode::LUT:
      primary = applyTransform(linearMm);
      break;
    default:
      primary = linearMm;
      break;
  }

  uint8_t w = 0;
  out[w++] = primary;
  if (m_mode == OutputMode::RAW && w < max) {
    out[w++] = linearMm;
  } else if (m_includeRaw && w < max) {
    out[w++] = float(sample.wrappedRaw);
  }
  if (m_includeRaw && w < max) {
    out[w++] = float(sample.unwrappedRaw);
  }
}

OutputConfig AS5600StringPotSensorBase::outputConfig() const {
  return OutputConfig{m_mode, m_includeRaw};
}

void AS5600StringPotSensorBase::setOutputConfig(const OutputConfig& cfg) {
  setOutputMode(cfg.primary);
  setIncludeRaw(cfg.includeRaw);
}

OutputMode AS5600StringPotSensorBase::outputMode() const {
  return m_mode;
}

void AS5600StringPotSensorBase::setOutputMode(OutputMode m) {
  m_mode = m;
}

bool AS5600StringPotSensorBase::beginCalibration(CalMode mode) {
  if(!ConfigManager::configurationMutable()) return false;
  if (mode == CalMode::NONE) return false;
  cal_ = CalState{};
  cal_.mode = mode;
  cal_.phase = CalPhase::ACTIVE;
  cal_.started_ms = millis();
  resetTrackingState(m_assumeTurn0AtStart);
  return true;
}

bool AS5600StringPotSensorBase::updateCalibration(int32_t latestCounts) {
  if(!ConfigManager::configurationMutable()) return false;
  if (cal_.phase != CalPhase::ACTIVE) return false;
  ++cal_.samples;

  if (cal_.mode == CalMode::ZERO) {
    cal_.first_counts = latestCounts;
  } else if (cal_.mode == CalMode::RANGE) {
    if (cal_.samples == 1) {
      cal_.first_counts = latestCounts;
    } else if (cal_.samples == 2) {
      cal_.second_counts = latestCounts;
    }
  }
  return true;
}

bool AS5600StringPotSensorBase::finishCalibration(bool persist) {
  if(!ConfigManager::configurationMutable()) return false;
  if (cal_.phase != CalPhase::ACTIVE) return false;

  if (cal_.mode == CalMode::ZERO) {
    const bool haveZero = (cal_.first_counts != INT32_MAX);
    const int32_t zero=haveZero ? cal_.first_counts : currentRawCounts();
    if(persist) { const char* keys[]={"installed_zero_count"};const String values[]={String(zero)};
      if(!ConfigManager::saveSensorParamsByName(name(),keys,values,1))return false; }
    installed_zero_count_=zero;
  } else if (cal_.mode == CalMode::RANGE) {
    const bool haveFirst = (cal_.first_counts != INT32_MAX);
    const bool haveSecond = (cal_.second_counts != INT32_MIN);
    if (!haveFirst || !haveSecond || cal_.first_counts == cal_.second_counts) {
      cal_.phase = CalPhase::COMPLETE;
      cal_.mode = CalMode::NONE;
      return false;
    }

    if(persist) { const char* keys[]={"sensor_zero_count","sensor_full_count"};
      const String values[]={String(cal_.first_counts),String(cal_.second_counts)};
      if(!ConfigManager::saveSensorParamsByName(name(),keys,values,2))return false; }
    sensor_zero_count_ = cal_.first_counts;
    sensor_full_count_ = cal_.second_counts;
    m_invert = (sensor_full_count_ < sensor_zero_count_);
    recomputeScale();


  }

  cal_.phase = CalPhase::COMPLETE;
  cal_.mode = CalMode::NONE;
  return true;
}

int32_t AS5600StringPotSensorBase::currentRawCounts() const {
  return captureSample_().unwrappedRaw;
}

bool AS5600StringPotSensorBase::hasRawCounts() const {
#if BODAQS_PRODUCTION_RECORDING
  StringPotCountStream::Sample sample;
  return m_countStream.snapshot(sample) && !(sample.quality&(StringPotCountStream::InvalidInput|
      StringPotCountStream::Uncertain|StringPotCountStream::SettlingHeld|StringPotCountStream::Overflow));
#else
  return true;
#endif
}

bool AS5600StringPotSensorBase::readPreviewValue(OutputMode mode, float& value, char* unit, size_t unitCap) {
#if BODAQS_PRODUCTION_RECORDING
  StringPotCountStream::Sample sample;
  if(m_muted || !m_countStream.snapshot(sample) || (sample.quality&StringPotCountStream::InvalidInput)) return false;
  if(mode==OutputMode::RAW) {value=float(sample.unwrapped);copyField_(unit,unitCap,"counts");return true;}
  if(mode!=OutputMode::LINEAR || counts_per_mm_<=0 ||
     (sample.quality&(StringPotCountStream::Uncertain|StringPotCountStream::SettlingHeld))) return false;
  value=countsToMm_(sample.unwrapped);copyField_(unit,unitCap,linearUnit_(m_unitsLabel));return true;
#else
  if (mode == OutputMode::RAW) return Sensor::readPreviewValue(mode, value, unit, unitCap);
  if (mode != OutputMode::LINEAR || m_mode != OutputMode::LINEAR || m_muted) return false;

  float out[1] = {0.0f};
  sampleValues(out, 1);
  value = out[0];
  copyField_(unit, unitCap, m_outputUnitsLabel[0] ? m_outputUnitsLabel : "mm");
  return true;
#endif
}

CalibrationState AS5600StringPotSensorBase::calibration() const {
  CalibrationState cs;
  cs.mode = m_mode;
  if (m_mode == OutputMode::LINEAR && counts_per_mm_ > 0.0) {
    const float gain = (m_invert ? -1.0f : 1.0f) / float(counts_per_mm_);
    cs.scale = gain;
    cs.offset = -float(installed_zero_count_) * gain;
  }
  return cs;
}

bool AS5600StringPotSensorBase::setCalibration(const CalibrationState& s) {
  (void)s;
  return false;
}

void AS5600StringPotSensorBase::setIncludeRaw(bool b) {
  m_includeRaw = b;
}

void AS5600StringPotSensorBase::setOutputUnitsLabel(const char* u) {
  Sensor::setOutputUnitsLabel(linearUnit_(u));
}
