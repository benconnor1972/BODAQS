#include "CpuOccupancy.h"
#include "SparseCostProbe.h"
#include "../can-fd/common/network/bodaqs_can_link.h"
#include "../can-fd/common/protocol/bodaqs_timing.h"
#if defined(ARDUINO_ARCH_ESP32)
#include <esp_timer.h>
#endif
#include "CanMasterManager.h"
#include "ImuFlowDiagnostics.h"
#include "ControlPollingDiagnostics.h"
#include "../can-fd/common/transport/bodaqs_spi_bench.h"
#if BODAQS_SPI_BOUNDARY_TRACE
#include "../can-fd/common/transport/bodaqs_spi_trace.h"
#if !defined(BODAQS_SINGLE_NODE_IMU_ADC_SMOKE) || !BODAQS_SINGLE_NODE_IMU_ADC_SMOKE || !defined(BODAQS_MEASUREMENT_REPLY_CAPTURE) || !BODAQS_MEASUREMENT_REPLY_CAPTURE
#error "Boundary trace requires the explicit mixed reply-capture logger"
#endif
#endif

#include <Arduino.h>
#include <SPI.h>
#include <esp_system.h>
#include <string.h>
#include <atomic>
#include <new>
#include <cstdlib>
#if defined(BODAQS_PACKED_EXCHANGE) && BODAQS_PACKED_EXCHANGE
#include "../can-fd/common/protocol/packed_receiver.h"
#if defined(ARDUINO_ARCH_ESP32)
#include <esp_heap_caps.h>
#endif
#endif

#include "CanMasterProtocol.h"
#include "CanMasterDiscovery.h"
#include "DebugLog.h"
#include "LoggingManager.h"
#include "SensorManager.h"
#include "SensorAssignment.h"
#include "Lsm6dso32xConfig.h"
#include "SharedSpiBus.h"
#include "../can-fd/common/protocol/bodaqs_control_snapshot.h"

#define CANMASTER_LOGI(...) LOGI_TAG("CANMASTER", __VA_ARGS__)
#define CANMASTER_LOGW(...) LOGW_TAG("CANMASTER", __VA_ARGS__)

// Bench-only start pacing; ordinary builds retain the existing dispatch rhythm.
#ifndef BODAQS_MEASUREMENT_START_SPACING_US
#define BODAQS_MEASUREMENT_START_SPACING_US 0
#endif
// Opt-in measurement-only CS setup experiment; normal/legacy calls stay at0.
#ifndef BODAQS_MEASUREMENT_CS_SETUP_US
#define BODAQS_MEASUREMENT_CS_SETUP_US 0
#endif

namespace {

constexpr uint32_t kAbsentProbeIntervalMs = 5000;
constexpr uint32_t kPresentProbeIntervalMs = 30000;
// Include four fetches so a failed exchange spans five physical slots. An
// even-length exchange can repeatedly lose its command to alternating RX
// queue overruns while only its fetches reach the master.
constexpr uint8_t kFetchAttempts = 4;
constexpr uint8_t kInventorySnapshotAttempts = 3;
constexpr uint32_t kSpiLockTimeoutMs = 10;
constexpr uint32_t kInterSlotGuardUs = 1000;
constexpr uint32_t kNodeStatusFlagErrorPassive = 1UL << 2;
constexpr uint32_t kNodeStatusFlagClockFault = 1UL << 8;

const board::BoardProfile* s_board = nullptr;
board::CanFdMasterProfile s_profile;
CanMasterManager::Diagnostics s_diagnostics;
uint32_t s_nextSequence = 1;
struct ModeInspection {
  uint32_t token=0,startedMs=0;
  uint64_t boot=0,context=0;
  bool ready=false;
} s_modeInspection;
struct ExitRecovery {
  BodaqsMeasurementMode binding={};
  uint32_t sequence=0;
  bool pending=false;
} s_exitRecovery;
uint32_t s_nextProbeMs = 0;
bool s_started = false;
bool s_probeRequested = false;
bool s_wasLogging = false;
bool s_lastIrqAsserted = false;
bool s_haveCompletedSlot = false;
uint32_t s_lastSlotCompletedUs = 0;
uint64_t s_statusHardwareUid = 0;
uint32_t s_nextControlMs = 0;
uint64_t s_lastConfirmedMasterBoot = 0;
uint64_t s_lastIssuedSession = 0;
bool s_renewSession = false;
uint32_t s_nextRecoveryMs[4] = {};
uint8_t s_exchangeOwner = 0;
uint32_t s_exchangeStartedMs = 0;
BodaqsControlWrapped s_exchangeIdentity = {};
uint32_t s_nextAuthorityRetryMs[4] = {};
uint8_t s_applyCursor = 0;


uint64_t freshSession_(uint64_t previous) {
  for (uint8_t attempt=0; attempt<4; ++attempt) {
    const uint64_t value=(static_cast<uint64_t>(esp_random())<<32)|esp_random();
    if (value && value!=previous && value!=s_lastIssuedSession) { s_lastIssuedSession=value; return value; }
  }
  return 0; // Entropy failure excludes control; never reuse an exhausted identity.
}

bool s_recordingFence = false;
bool s_handoffReady = false;
uint32_t s_handoffStartedMs = 0;
// Client knowledge expires after 5 s. One 100 ms service cadence plus 400 ms
// scheduling allowance bounds the logger handoff; this is not a wire cancel.
constexpr uint32_t kRecordingHandoffMs = 5500;

// Saved ownership plus live mute selects explicit disable. An active unresolved
// remote BMI owner is retained as unresolved; it cannot become a new profile.
bool s_configurationDirty[4] = {};

bool desiredDisabled_(uint8_t address) {
  const auto& cfg = ConfigManager::get();
  for (uint8_t i = 0; i < cfg.sensorCount(); ++i) {
    SensorSpec spec;
    if (!cfg.getSensorSpec(i, spec)) continue;
    const auto assignment = sensorAssignment(spec, s_board);
    if (assignment.provider.kind != SensorProviderKind::CanNode ||
        assignment.provider.index != address || assignment.kind != SensorAssignment::Kind::NodeImu) continue;
    bool muted = spec.mutedDefault;
    (void)SensorManager::getMuted(i, muted);
    if (!muted) return false;
  }
  return true;
}

bool desiredEnabled_(uint8_t address) {
  const auto& cfg=ConfigManager::get();
  unsigned owners=0; bool enabled=false;
  for(uint8_t i=0;i<cfg.sensorCount();++i) {
    SensorSpec spec; if(!cfg.getSensorSpec(i,spec)) continue;
    const auto assignment=sensorAssignment(spec,s_board);
    if(assignment.provider.kind!=SensorProviderKind::CanNode || assignment.provider.index!=address ||
       assignment.kind!=SensorAssignment::Kind::NodeImu) continue;
    ++owners; bool muted=spec.mutedDefault; (void)SensorManager::getMuted(i,muted);
    char error[128];
    enabled=!muted && spec.type==SensorType::LSM6DSO32XImu && Lsm6dso32xConfig::validateSpec(spec,error,sizeof(error));
  }
  return owners==1 && enabled;
}

uint8_t desiredProfile_(uint8_t address) {
  const auto& cfg=ConfigManager::get();
  for(uint8_t i=0;i<cfg.sensorCount();++i) {
    SensorSpec spec;if(!cfg.getSensorSpec(i,spec))continue;
    const auto a=sensorAssignment(spec,s_board);
    if(a.provider.kind==SensorProviderKind::CanNode && a.provider.index==address &&
       a.kind==SensorAssignment::Kind::NodeImu && spec.type==SensorType::LSM6DSO32XImu)
      return Lsm6dso32xConfig::profileId(spec);
  }
  return 0;
}

void scheduleDisabled_() {
  if (LoggingManager::configurationLocked() || s_recordingFence) return;
  for (uint8_t turn = 0; turn < 4; ++turn) {
#if BODAQS_PRODUCTION_RECORDING
    const uint8_t address = (s_applyCursor + turn) % 4;
#else
    const uint8_t address = turn;
#endif
    const bool disabled = desiredDisabled_(address);
    const bool enabled = desiredEnabled_(address);
    auto& generation = s_diagnostics.desiredGeneration[address];
    if (!generation || s_configurationDirty[address] || disabled != s_diagnostics.desiredDisabled[address] ||
        enabled != s_diagnostics.desiredEnabled[address]) {
      if (generation == UINT64_MAX) { s_renewSession=true; continue; }
      ++generation;
      s_configurationDirty[address]=false;
      s_diagnostics.desiredEnabled[address]=enabled;
      s_diagnostics.desiredDisabled[address] = disabled;
      // Preserve an in-flight operation; a changed desired state is picked up
      // after its terminal result and fresh observation.
    }
    auto& outcome = s_diagnostics.apply.nodes[address];
    if (s_diagnostics.apply.phase || (!disabled && !enabled) ||
        CanMasterManager::configurationReconciled(address)) continue;
    // An uncertain admission cannot be made safe by changing the desired payload.
    // Inspect fresh effective state, then renew scope before another mutation.
    if (outcome.valid && outcome.session==s_diagnostics.authority.session &&
        (outcome.kind==6 || (outcome.kind==1 && (outcome.reason==5 || outcome.reason==12)))) continue;
    if (outcome.valid && outcome.desired_generation == generation &&
        outcome.boot == s_diagnostics.control.nodes[address].node_boot_id &&
        outcome.session == s_diagnostics.authority.session &&
        static_cast<int32_t>(millis()-s_nextRecoveryMs[address])<0) continue;
    const auto& node = s_diagnostics.control.nodes[address];
    const auto& endpoint = node.endpoints[0];
    if (!node.available || !(node.endpoint_mask & 1) || !endpoint.current ||
        !endpoint.capability_valid || !endpoint.effective_valid ||
        (bodaqs_control_get_u32(endpoint.capability + 8) & 3) != 3) continue;
    uint8_t descriptor[44] = {1,0,1,0};
    if(enabled) { descriptor[4]=descriptor[10]=1;descriptor[8]=desiredProfile_(address); }
    if (bodaqs_control_apply_client_start(&s_diagnostics.apply, &s_diagnostics.authority,
        s_diagnostics.control.master_boot_id, address, generation,
        bodaqs_control_get_u64(endpoint.effective + 32), descriptor, millis())) {
      s_diagnostics.control.nodes[address].endpoints[0].current=false;
      s_nextRecoveryMs[address]=millis()+30000;
      s_applyCursor = (address+1)%4;
      return;
    }
  }
}

#if BODAQS_PRODUCTION_RECORDING
uint8_t idlePreparationMask_() {
  uint8_t mask=0;
  for(uint8_t n=0;n<4;++n)
    if((desiredEnabled_(n) || desiredDisabled_(n)) && !CanMasterManager::configurationReconciled(n))
      mask |= uint8_t(1u<<n);
  return mask;
}
#endif

uint8_t spiDataMode_(uint8_t mode) {
  switch (mode) {
    case 1: return SPI_MODE1;
    case 2: return SPI_MODE2;
    case 3: return SPI_MODE3;
    case 0:
    default: return SPI_MODE0;
  }
}

bool due_(uint32_t now, uint32_t deadline) {
  return static_cast<int32_t>(now - deadline) >= 0;
}

uint32_t nextSequence_() {
  const uint32_t sequence = s_nextSequence++;
  if (s_nextSequence == 0) s_nextSequence = 1;
  return sequence;
}

void clearStatus_() {
  s_diagnostics.statusSupported = false;
  s_diagnostics.statusValid = false;
  s_diagnostics.statusFlags = 0;
  s_diagnostics.masterUptimeMs = 0;
  s_diagnostics.masterResetCause = 0;
  s_diagnostics.masterSlotsReceived = 0;
  s_diagnostics.masterMalformedSlots = 0;
  s_diagnostics.masterProbesReceived = 0;
  s_diagnostics.masterStatusRequestsReceived = 0;
  s_diagnostics.masterSpiRecoveries = 0;
  s_diagnostics.canRxFrames = 0;
  s_diagnostics.canTxFrames = 0;
  s_diagnostics.canErrorEvents = 0;
  s_diagnostics.canRxQueueDepth = 0;
  s_diagnostics.canRxQueueHighWater = 0;
  s_diagnostics.spiTxQueueDepth = 0;
  s_diagnostics.spiTxQueueHighWater = 0;
}

void clearInventory_(bool clearObservations) {
  s_diagnostics.inventorySupported = false;
  s_diagnostics.inventoryValid = false;
  s_diagnostics.inventoryGeneration = 0;
  s_diagnostics.inventoryNodeCount = 0;
  s_diagnostics.inventoryPresentCount = 0;
  s_diagnostics.inventoryStaleCount = 0;
  s_diagnostics.inventoryDuplicateCount = 0;
  memset(s_diagnostics.inventory, 0, sizeof(s_diagnostics.inventory));
  if (clearObservations) {
    SensorManager::clearRemoteDiscoveryObservations();
  }
  for (uint8_t address = 0; address < 4; ++address) {
    bodaqs_control_observer_node(&s_diagnostics.control, address, 0, 0, false);
    bodaqs_control_authority_client_node(&s_diagnostics.authority, address, 0, false);
    bodaqs_control_apply_client_invalidate(&s_diagnostics.apply, address);
  }
}

void clearControl_() {
  s_diagnostics.controlSupported = false;
  s_diagnostics.controlInfoValid = false;
  bodaqs_control_observer_boot(&s_diagnostics.control, 0, 0);
}

void clearIdentity_() {
  clearControl_();
  s_diagnostics.compatible = false;
  s_diagnostics.protocolVersion = 0;
  s_diagnostics.firmwareVersion = 0;
  s_diagnostics.capabilities = 0;
  s_diagnostics.hardwareUid = 0;
  s_diagnostics.statusSupported = false;
  s_diagnostics.statusValid = false;
  clearInventory_(true);
}

void refreshInventoryIfStateChanged_(CanMasterManager::State previous,
                                     bool inventoryCommitted = false) {
  if (previous == s_diagnostics.state) return;
  if (s_diagnostics.state != CanMasterManager::State::Present) {
    SensorManager::clearRemoteDiscoveryObservations();
  }
  if (!inventoryCommitted) {
    SensorManager::discoverHardware(
        SensorManager::DiscoveryReason::TransportUpdate);
  }
}

bool transferSlot_(
    const SPISettings& settings, const uint8_t* tx, uint8_t* rx,
    size_t length = CanMasterProtocol::kSlotBytes, uint32_t guardUs = kInterSlotGuardUs,
    uint32_t minimumStartSpacingUs = 0, uint32_t csSetupUs = 0,
    SpiTransactionContext* context = nullptr
#if BODAQS_ACQUISITION_PROFILE
    , SpiTransferTiming* profileTiming = nullptr
#endif
    ) {
  if (s_haveCompletedSlot) {
    const uint32_t elapsedUs = micros() - s_lastSlotCompletedUs;
    if (elapsedUs < guardUs) {
      delayMicroseconds(guardUs - elapsedUs);
    }
  }
  if (!SharedSpiBus::transfer(
          s_profile.cs_pin, settings, tx, rx,
          length, kSpiLockTimeoutMs, minimumStartSpacingUs, csSetupUs, context
#if BODAQS_ACQUISITION_PROFILE
          ,profileTiming
#endif
          )) {
    return false;
  }
  s_lastSlotCompletedUs = micros();
  s_haveCompletedSlot = true;
  return true;
}

bool transferFrame_(
    const CanMasterProtocol::Frame& request,
    CanMasterProtocol::Frame& response) {
  if ((s_diagnostics.measurementUnavailable || s_diagnostics.measurement.phase != 0) &&
      static_cast<unsigned>(request.type) != 8 && static_cast<unsigned>(request.type) != 9 &&
      static_cast<unsigned>(request.type) != 10 &&
      !( !LoggingManager::isRunning() &&
         (static_cast<unsigned>(request.type)==4 || static_cast<unsigned>(request.type)==6 ||
          static_cast<unsigned>(request.type)==7))) return false;
  uint8_t tx[CanMasterProtocol::kSlotBytes];
  uint8_t rx[CanMasterProtocol::kSlotBytes];
  if (!CanMasterProtocol::encodeSlot(request, tx, sizeof(tx))) return false;
  const SPISettings settings(
      (static_cast<unsigned>(request.type)>=8 && static_cast<unsigned>(request.type)<=10)
          ? 4000000UL : (s_profile.spi_hz ? s_profile.spi_hz : 1000000UL),
      MSBFIRST,
      spiDataMode_(s_profile.spi_mode));
  if (!transferSlot_(settings, tx, rx)) {
    ++s_diagnostics.transferFailures;
    return false;
  }

  // SPI is full duplex, so a command's response is returned in a later slot.
  // Accept a response already queued during the command transaction, then issue
  // bounded fetch slots while the master prepares a new one.
  if (CanMasterProtocol::decodeSlot(rx, sizeof(rx), response) ==
          CanMasterProtocol::DecodeResult::Ok &&
      response.sequence == request.sequence) {
    return true;
  }

  CanMasterProtocol::Frame fetch;
  fetch.type = CanMasterProtocol::MessageType::FetchResponse;
  fetch.sequence = request.sequence;
  if (!CanMasterProtocol::encodeSlot(fetch, tx, sizeof(tx))) return false;
  for (uint8_t attempt = 0; attempt < kFetchAttempts; ++attempt) {
    memset(rx, 0, sizeof(rx));
    if (!transferSlot_(settings, tx, rx)) {
      ++s_diagnostics.transferFailures;
      return false;
    }
    if (CanMasterProtocol::decodeSlot(rx, sizeof(rx), response) ==
            CanMasterProtocol::DecodeResult::Ok &&
        response.sequence == request.sequence) {
      return true;
    }
  }
  ++s_diagnostics.invalidResponses;
  return false;
}

bool refreshStatus_() {
  if (!s_diagnostics.statusSupported) return false;
  ++s_diagnostics.statusAttempts;

  CanMasterProtocol::Frame request;
  request.type = CanMasterProtocol::MessageType::StatusRequest;
  request.sequence = nextSequence_();
  CanMasterProtocol::Frame response;
  CanMasterProtocol::Status status;
  if (!transferFrame_(request, response) ||
      !CanMasterProtocol::decodeStatus(response, status)) {
    s_diagnostics.statusValid = false;
    ++s_diagnostics.statusFailures;
    return false;
  }

  s_diagnostics.statusValid = true;
  s_statusHardwareUid = s_diagnostics.hardwareUid;
  ++s_diagnostics.statusSuccesses;
  s_diagnostics.lastStatusMs = millis();
  s_diagnostics.statusFlags = status.flags;
  s_diagnostics.masterUptimeMs = status.uptimeMs;
  s_diagnostics.masterResetCause = status.resetCause;
  s_diagnostics.masterSlotsReceived = status.slotsReceived;
  s_diagnostics.masterMalformedSlots = status.malformedSlots;
  s_diagnostics.masterProbesReceived = status.probesReceived;
  s_diagnostics.masterStatusRequestsReceived = status.statusRequestsReceived;
  s_diagnostics.masterSpiRecoveries = status.spiRecoveries;
  s_diagnostics.canRxFrames = status.canRxFrames;
  s_diagnostics.canTxFrames = status.canTxFrames;
  s_diagnostics.canErrorEvents = status.canErrorEvents;
  s_diagnostics.canRxQueueDepth = status.canRxQueueDepth;
  s_diagnostics.canRxQueueHighWater = status.canRxQueueHighWater;
  s_diagnostics.spiTxQueueDepth = status.spiTxQueueDepth;
  s_diagnostics.spiTxQueueHighWater = status.spiTxQueueHighWater;
  return true;
}

bool refreshControlInfo_() {
  if (!s_diagnostics.controlSupported) {
    clearControl_();
    return false;
  }
  CanMasterProtocol::Frame request, response;
  request.type = CanMasterProtocol::MessageType::ControlInfoRequest;
  request.sequence = nextSequence_();
  uint64_t boot = 0;
  uint32_t features = 0;
  if (!transferFrame_(request, response) ||
      response.type != CanMasterProtocol::MessageType::ControlInfoResponse ||
      response.flags != 0 ||
      !bodaqs_control_decode_info(response.payload, response.payloadLength,
                                 &boot, &features)) {
    s_diagnostics.controlInfoValid = false;
    bodaqs_control_observer_boot(&s_diagnostics.control, 0, 0);
    ++s_diagnostics.invalidResponses;
    return false;
  }
  if (s_lastConfirmedMasterBoot && s_lastConfirmedMasterBoot != boot)
    s_renewSession = true;
  s_lastConfirmedMasterBoot = boot;
  if (s_renewSession && !LoggingManager::configurationLocked() && !s_recordingFence) {
    CanMasterManager::enableControlAuthority(freshSession_(s_diagnostics.authority.session));
    s_renewSession = false;
  }
  bodaqs_control_observer_boot(&s_diagnostics.control, boot, features);
  s_diagnostics.controlInfoValid = true;
  return true;
}

void serviceControl_() {
  if (!s_diagnostics.controlInfoValid || !s_diagnostics.inventoryValid) return;
  const uint32_t now=millis();
  const uint8_t pendingOwner=s_diagnostics.apply.pending ? 2 :
      s_diagnostics.authority.pending ? 3 : s_diagnostics.control.pending ? 1 : 0;
  if (pendingOwner && pendingOwner==s_exchangeOwner &&
      static_cast<uint32_t>(now-s_exchangeStartedMs)>=3500) {
    // The SPI path and malformed cached replies need their own local deadline.
    // Abandon transport ownership, never assert cancellation of admitted hardware.
    if (pendingOwner==2) {
      bodaqs_control_apply_client_transport_timeout(&s_diagnostics.apply, now);
    } else if (pendingOwner==3) {
      const uint8_t address=s_diagnostics.authority.current.node_address;
      bodaqs_control_authority_client_transport_timeout(&s_diagnostics.authority);
      s_nextAuthorityRetryMs[address]=now+5000;
    } else {
      s_diagnostics.control.pending=false;
      s_diagnostics.control.snapshot_phase=0;
      const uint8_t address=s_diagnostics.control.current.node_address;
      s_diagnostics.control.retry_after_ms[address]=now+5000;
      auto& node=s_diagnostics.control.nodes[address];
      node.valid=false;node.epoch_valid_mask=0;
      for(auto& endpoint:node.endpoints) endpoint.current=false;
    }
    s_exchangeOwner=0;
  }
  if (!LoggingManager::configurationLocked() && !s_recordingFence) {
    for(uint8_t address=0;address<4;++address) {
      auto& peer=s_diagnostics.authority.nodes[address];
      const auto& outcome=s_diagnostics.apply.nodes[address];
      if(peer.available && peer.phase==3 && peer.reason && due_(now,s_nextAuthorityRetryMs[address])) {
        if(peer.reason==5 || peer.reason==12 || (peer.reason==20 && peer.ever_bound)) s_renewSession=true;
        else {
          if(peer.reason==20) peer.bind={}; // An unconsumed challenge can expire while a prior apply drains.
          peer.phase=peer.bind.record.opcode ? 1 : 0;
        }
        s_nextAuthorityRetryMs[address]=now+5000;
      }
      const auto& endpoint=s_diagnostics.control.nodes[address].endpoints[0];
      const bool uncertain=outcome.kind==6 ||
          (outcome.kind==1 && (outcome.reason==5 || outcome.reason==12));
      if(peer.available && ((peer.bound && !peer.next_mutation) ||
         (outcome.valid && uncertain && outcome.session==s_diagnostics.authority.session &&
          endpoint.current && static_cast<int32_t>(endpoint.observed_ms-outcome.observed_ms)>=0 &&
          !CanMasterManager::configurationReconciled(address))))
        s_renewSession=true;
    }
    if(!s_diagnostics.authority.next_read || s_diagnostics.apply.next_transfer==UINT64_MAX)
      s_renewSession=true;
    if(s_renewSession && !s_diagnostics.apply.phase && !s_diagnostics.authority.pending &&
       !s_diagnostics.control.pending && !s_diagnostics.control.snapshot_phase) {
      CanMasterManager::enableControlAuthority(freshSession_(s_diagnostics.authority.session));
      s_renewSession=false;
    }
  }
  BodaqsControlWrapped wrapped, reply;
  uint8_t type;
  bodaqs_control_observer_tick(&s_diagnostics.control, millis());
  const bool observerOwnsExchange = s_diagnostics.control.pending || s_diagnostics.control.snapshot_phase;
  if (!observerOwnsExchange && !s_diagnostics.authority.pending) scheduleDisabled_();
  const bool applyRequest = !observerOwnsExchange && !s_diagnostics.authority.pending &&
      ((!LoggingManager::configurationLocked() && !s_recordingFence) || s_diagnostics.apply.pending ||
       (s_recordingFence && !s_handoffReady && s_diagnostics.apply.commit_sent && s_diagnostics.apply.phase == 5)) &&
      bodaqs_control_apply_client_next(&s_diagnostics.apply, &s_diagnostics.authority,
          millis(), &wrapped, &type);
  const bool authorityOwnsExchange = !observerOwnsExchange &&
      !applyRequest && !s_diagnostics.apply.phase &&
      (s_diagnostics.authority.pending || (!LoggingManager::configurationLocked() && !s_recordingFence));
  const bool authorityRequest = authorityOwnsExchange &&
      bodaqs_control_authority_client_next(&s_diagnostics.authority,
          s_diagnostics.control.master_boot_id, &wrapped, &type);
  if (!authorityRequest && !applyRequest && s_recordingFence &&
      !s_diagnostics.control.pending && !s_diagnostics.control.snapshot_phase) return;
  if (!authorityRequest && !applyRequest && !bodaqs_control_observer_next(&s_diagnostics.control, &wrapped, &type)) return;
  const uint8_t owner=applyRequest ? 2 : authorityRequest ? 3 : 1;
  if(owner!=s_exchangeOwner || memcmp(&wrapped.record,&s_exchangeIdentity.record,
      offsetof(BodaqsControlRecord,data_length)) ||
     wrapped.node_address!=s_exchangeIdentity.node_address ||
     wrapped.record.operation!=s_exchangeIdentity.record.operation ||
     wrapped.record.transfer!=s_exchangeIdentity.record.transfer ||
     wrapped.record.opcode!=s_exchangeIdentity.record.opcode) {
    s_exchangeOwner=owner;s_exchangeStartedMs=now;s_exchangeIdentity=wrapped;
  }
  CanMasterProtocol::Frame request, response;
  request.type = static_cast<CanMasterProtocol::MessageType>(type);
  request.sequence = nextSequence_();
  request.payloadLength = 64;
  if (!bodaqs_control_encode_wrapped(&wrapped, request.payload) ||
      !transferFrame_(request, response) || response.flags != 0 ||
      (response.type != CanMasterProtocol::MessageType::ControlReceiptResponse &&
       response.type != CanMasterProtocol::MessageType::ControlPollResponse) ||
      !bodaqs_control_decode_wrapped(response.payload, response.payloadLength, &reply)) {
    ++s_diagnostics.invalidResponses;
    for (auto& node : s_diagnostics.control.nodes) {
      node.valid = false;
      node.epoch_valid_mask = 0;
      for(auto& endpoint:node.endpoints) endpoint.current=false;
    }
    return;
  }
  const bool accepted = applyRequest ?
      bodaqs_control_apply_client_accept(&s_diagnostics.apply, &s_diagnostics.authority,
          static_cast<uint8_t>(response.type), &reply, millis()) : authorityRequest ?
      bodaqs_control_authority_client_accept(&s_diagnostics.authority,
          static_cast<uint8_t>(response.type), &reply, millis()) :
      bodaqs_control_observer_accept(&s_diagnostics.control,
          static_cast<uint8_t>(response.type), &reply, millis());
  if (!accepted) {
    ++s_diagnostics.invalidResponses;
  } else if (!authorityRequest && !applyRequest && reply.record.opcode == BODAQS_CONTROL_GET_NODE_STATE &&
             reply.record.endpoint == BODAQS_CONTROL_NODE_WIDE &&
             response.type == CanMasterProtocol::MessageType::ControlPollResponse) {
    bodaqs_control_authority_client_observe_session(&s_diagnostics.authority,
        reply.node_address, s_diagnostics.control.nodes[reply.node_address].active_session);
  }
  if (!(applyRequest ? s_diagnostics.apply.pending : authorityRequest ?
      s_diagnostics.authority.pending : s_diagnostics.control.pending)) s_exchangeOwner=0;
  if (reply.master_boot_id != wrapped.master_boot_id) {
    s_diagnostics.controlInfoValid = false;
    s_probeRequested = true;
  }
}

void stageEndpoint_(const CanMasterProtocol::DiscoveryRecord& record,
                    SensorProviderId provider, uint8_t endpoint,
                    bool present, bool healthy) {
  if ((record.endpointMask & (1U << endpoint)) == 0) return;

  SensorEndpointObservation observation;
  observation.endpoint.provider = provider;
  observation.present = present;
  observation.healthy = healthy;
  observation.deviceIdentity = static_cast<uint32_t>(record.hardwareUid);
  observation.capabilities = CanMasterDiscovery::endpointTypeCapabilities(endpoint);
  switch (endpoint) {
    case 0:
      observation.endpoint.kind = SensorAssignment::Kind::NodeImu;
      observation.endpoint.input = 0;
      break;
    case 1:
    case 2:
      observation.endpoint.kind = SensorAssignment::Kind::NodeAnalog;
      observation.endpoint.input = endpoint - 1;
      break;
    case 3:
    case 4:
      observation.endpoint.kind = SensorAssignment::Kind::NodeI2C;
      observation.endpoint.input = endpoint - 3;
      break;
    default:
      return;
  }
  (void)SensorManager::setRemoteEndpointObservation(observation);
}

void commitInventory_(
    const CanMasterProtocol::DiscoveryRecord* records,
    uint32_t generation) {
  SensorManager::clearRemoteDiscoveryObservations();
  s_diagnostics.inventoryPresentCount = 0;
  s_diagnostics.inventoryStaleCount = 0;
  s_diagnostics.inventoryDuplicateCount = 0;

  for (uint8_t node = 0; node < CanMasterProtocol::kDiscoveryNodeCount;
       ++node) {
    const auto& record = records[node];
    const bool identityChanged=s_diagnostics.inventory[node].hardwareUid &&
        s_diagnostics.inventory[node].hardwareUid!=record.hardwareUid;
    if(identityChanged) {
      bodaqs_control_observer_node(&s_diagnostics.control,node,record.bootId,record.endpointMask,false);
      bodaqs_control_authority_client_node(&s_diagnostics.authority,node,record.bootId,false);
      bodaqs_control_apply_client_invalidate(&s_diagnostics.apply,node);
      s_renewSession=true;
    }
    s_diagnostics.inventory[node] = record;
    const bool present =
        (record.flags & CanMasterProtocol::kDiscoveryFlagPresent) != 0;
    const bool stale =
        (record.flags & CanMasterProtocol::kDiscoveryFlagStale) != 0;
    const bool duplicate =
        (record.flags & CanMasterProtocol::kDiscoveryFlagDuplicate) != 0;
    const bool statusValid =
        (record.flags & CanMasterProtocol::kDiscoveryFlagStatusValid) != 0;
    bool healthy = present && !stale && !duplicate;
    if (statusValid &&
        (record.nodeStatusFlags &
         (kNodeStatusFlagErrorPassive | kNodeStatusFlagClockFault)) != 0) {
      healthy = false;
    }
    const bool available=present && !stale && !duplicate;
    if (available && (!s_diagnostics.control.nodes[node].available ||
        s_diagnostics.control.nodes[node].node_boot_id != record.bootId)) {
      s_nextRecoveryMs[node]=millis();
      s_nextAuthorityRetryMs[node]=millis();
    }
    if (s_diagnostics.control.nodes[node].node_boot_id != record.bootId || !available)
      bodaqs_control_apply_client_invalidate(&s_diagnostics.apply, node);
    bodaqs_control_observer_node(&s_diagnostics.control, node, record.bootId,
        record.endpointMask, present && !stale && !duplicate);
    bodaqs_control_authority_client_node(&s_diagnostics.authority, node, record.bootId,
        present && !stale && !duplicate);
    if (present) ++s_diagnostics.inventoryPresentCount;
    if (stale) ++s_diagnostics.inventoryStaleCount;
    if (duplicate) ++s_diagnostics.inventoryDuplicateCount;

    SensorProviderId provider;
    provider.kind = SensorProviderKind::CanNode;
    provider.index = node;
    SensorProviderObservation providerObservation;
    providerObservation.id = provider;
    providerObservation.present = present;
    providerObservation.healthy = healthy;
    providerObservation.hardwareUid = record.hardwareUid;
    providerObservation.capabilities =
        CanMasterDiscovery::providerTypeCapabilities(record.endpointMask);
    providerObservation.protocolVersion = CanMasterProtocol::kProtocolVersion;
    (void)SensorManager::setRemoteProviderObservation(providerObservation);

    for (uint8_t endpoint = 0; endpoint <= 4; ++endpoint) {
      stageEndpoint_(record, provider, endpoint, present, healthy);
    }
  }

  s_diagnostics.inventoryValid = true;
  s_diagnostics.inventoryGeneration = generation;
  s_diagnostics.inventoryNodeCount = CanMasterProtocol::kDiscoveryNodeCount;
  s_diagnostics.lastInventoryMs = millis();
  ++s_diagnostics.inventorySuccesses;
  SensorManager::discoverHardware(SensorManager::DiscoveryReason::TransportUpdate);
}

bool refreshInventory_() {
  if (!s_diagnostics.inventorySupported) return false;
  ++s_diagnostics.inventoryAttempts;

  for (uint8_t snapshotAttempt = 0;
       snapshotAttempt < kInventorySnapshotAttempts; ++snapshotAttempt) {
    CanMasterProtocol::DiscoveryRecord
        records[CanMasterProtocol::kDiscoveryNodeCount];
    uint32_t generation = 0;
    bool valid = true;
    bool generationChanged = false;

    for (uint8_t node = 0; node < CanMasterProtocol::kDiscoveryNodeCount;
         ++node) {
      CanMasterProtocol::Frame request;
      if (!CanMasterProtocol::encodeDiscoveryRequest(
              node, generation, nextSequence_(), request)) {
        valid = false;
        break;
      }
      CanMasterProtocol::Frame response;
      if (!transferFrame_(request, response)) {
        valid = false;
        break;
      }
      if (!CanMasterProtocol::decodeDiscoveryResponse(
              response, records[node]) ||
          records[node].nodeAddress != node) {
        ++s_diagnostics.invalidResponses;
        valid = false;
        break;
      }
      if (node == 0) {
        generation = records[node].generation;
      } else if (records[node].generation != generation) {
        generationChanged = true;
        valid = false;
        break;
      }
    }

    if (valid) {
      commitInventory_(records, generation);
      return true;
    }
    if (generationChanged &&
        snapshotAttempt + 1 < kInventorySnapshotAttempts) {
      ++s_diagnostics.inventorySnapshotRetries;
      continue;
    }
    break;
  }

  s_diagnostics.inventoryValid = false;
  ++s_diagnostics.inventoryFailures;
  return false;
}

}  // namespace

namespace CanMasterManager {
#if defined(BODAQS_PACKED_EXCHANGE) && BODAQS_PACKED_EXCHANGE
#include "CanMasterPacked.h"
#endif

static std::atomic<bool (*)()> s_measurementOwner{nullptr};
static bool s_restartCleanupNeeded=false;
static bool measurementAccess_() { auto owner=s_measurementOwner.load();return !owner || owner(); }
#if defined(BODAQS_PACKED_STARTUP_DIAGNOSTICS) && BODAQS_PACKED_STARTUP_DIAGNOSTICS
uint8_t measurementControlBlockers() {
  return (s_measurementOwner?1u:0u)|(!s_recordingFence?2u:0u)|(!s_handoffReady?4u:0u)|
      (s_diagnostics.apply.phase?8u:0u)|(s_diagnostics.authority.pending?16u:0u)|
      (s_diagnostics.control.pending?32u:0u);
}
#endif
bool claimMeasurementControl(bool (*owner)()) {
  if (!owner || s_measurementOwner || !s_recordingFence || !s_handoffReady ||
      s_diagnostics.apply.phase || s_diagnostics.authority.pending || s_diagnostics.control.pending) return false;
  s_measurementOwner=owner;
  return true;
}
void releaseMeasurementControl() {
  if (s_measurementOwner && measurementAccess_() && !s_diagnostics.measurementUnavailable &&
      !s_diagnostics.measurement.phase) s_measurementOwner=nullptr;
}
void retainMeasurementAllocators(uint32_t read,const uint32_t mutations[4],uint64_t transfer) {
  if (!s_measurementOwner || !measurementAccess_()) return;
  s_diagnostics.authority.next_read=read;
  for(uint8_t n=0;n<4;++n) s_diagnostics.authority.nodes[n].next_mutation=mutations[n];
  s_diagnostics.apply.next_transfer=transfer;
}

static bool modeObservation_(const BodaqsMeasurementSlot&,uint32_t,uint64_t,const BodaqsMeasurementMode*);
#if BODAQS_SPI_BOUNDARY_TRACE
static void freezeBoundary_(uint64_t context) {
  if(!ImuFlowDiagnostics::active || ImuFlowDiagnostics::live.context!=context)return;
  auto& capture=ImuFlowDiagnostics::liveReplies;
  if(capture.count!=1 || capture.boundary.attempted)return;
  auto& probe=capture.boundary;const auto& failed=capture.entries[0];
  probe.attempted=true;probe.nonce=failed.slot;probe.failedDeviceSequence=failed.bus.deviceSequence;
  if(!failed.requestValid || !failed.bus.valid || !failed.bus.deviceSequenceValid ||
     !failed.slot || failed.slot==UINT32_MAX)return;
  static BodaqsMeasurementSlot marker;
  alignas(4) static uint8_t tx[256],rx[256];
  bodaqs_spi_trace_request(&marker,context,failed.slot,failed.bus.deviceSequence,
      static_cast<uint32_t>(bodaqs_measurement_get(failed.request+252,4)),
      static_cast<uint32_t>(bodaqs_measurement_get(failed.reply+252,4)));
  if(!bodaqs_measurement_encode(&marker,tx,sizeof tx))return;
  SpiTransactionContext bus;
  const SPISettings settings(BODAQS_MEASUREMENT_HZ,MSBFIRST,spiDataMode_(s_profile.spi_mode));
  const uint32_t began=micros();
  // One diagnostic frame after the original exchange. Its pipelined reply is
  // discarded, never admitted or repaired. Master export proves freeze later.
  probe.transferred=transferSlot_(settings,tx,rx,sizeof tx,25,
      BODAQS_MEASUREMENT_START_SPACING_US,BODAQS_MEASUREMENT_CS_SETUP_US,&bus);
  probe.durationUs=micros()-began;probe.markerDeviceSequence=bus.deviceSequence;
  probe.adjacent=probe.transferred && bus.deviceSequenceValid &&
      bus.deviceSequence==failed.bus.deviceSequence+1;
}
#endif
static uint32_t measurementTimingStartUs,measurementTimingEndUs;
#if BODAQS_PIPELINE_TRACE
static uint32_t measurementPhysicalSequence;
static bool measurementPhysicalSequenceValid;
#endif
bool exchangeMeasurementSlot(const BodaqsMeasurementSlot& request,
                             BodaqsMeasurementSlot& response) {
#if BODAQS_PIPELINE_TRACE
  measurementPhysicalSequence=0;measurementPhysicalSequenceValid=false;
#endif
  if (!measurementAccess_()) return false;
  if (!s_started || !s_profile.supported || s_profile.cs_pin < 0 ||
      s_profile.spi_bus_index != 0 || s_diagnostics.mode == CanMasterMode::Off) return false;
  // Only the measurement owner may enter; storage never aliases DMA or an inbox.
  // Persistent buffers avoid adding two bulk frames to the 4 KiB task stack.
  static uint8_t tx[BODAQS_MEASUREMENT_BYTES], rx[BODAQS_MEASUREMENT_BYTES];
#if BODAQS_ACQUISITION_PROFILE
  const auto profileOwner=s_measurementOwner.load();
  const bool profileExchange=profileOwner && profileOwner();
  const uint32_t encodingStart=micros();
#endif
#if defined(BODAQS_PACKED_EXCHANGE) && BODAQS_PACKED_EXCHANGE
  const bool packedCommand=packedWanted && packedTransport && !packedTransport->recovering &&
      (request.kind==1 || request.kind==15 || ((request.kind==5 || request.kind==14) && packedTracksAck_(request)));
  packedCommandObserved_(packedCommand,micros());
  if(packedCommand){
    // bpr_command writes the complete meaningful command, including retries.
    // Preserve canonical physical padding without clearing overwritten bytes.
    memset(tx+BP_COMMAND_BYTES,0,sizeof tx-BP_COMMAND_BYTES);
#if BODAQS_PACKED_PROGRESS
    const uint32_t previousSequence=packedReceiver->sequence;
    const uint32_t previousMetadata=packedReceiver->metadata_sequence;
    if(!bpr_command_at(packedReceiver,tx,micros(),!LoggingManager::isRunning()))return false;
    if(packedReceiver->sequence!=previousSequence)++packedUtil.new_commands;else ++packedUtil.retries;
    const bool fresh=packedReceiver->metadata_sequence!=previousMetadata;
    if(fresh)packedAckStarted=micros();
    packedAckObserved_(fresh);
#else
    const bool fresh=!packedReceiver->awaiting;if(!bpr_command(packedReceiver,tx))return false;packedAckObserved_(fresh);
#endif
  }
  else
#endif
  {
#if BODAQS_SPI_BULK_BYTES
    // Bulk legacy commands encode only128 bytes; the encoder zeros that
    // extent itself. Non-bulk encoding initializes the complete frame.
    memset(tx+128,0,sizeof tx-128);
#endif
    if (!bodaqs_measurement_encode_request(&request, tx, sizeof tx)) return false;
  }
  const SPISettings settings(BODAQS_MEASUREMENT_HZ, MSBFIRST, spiDataMode_(s_profile.spi_mode));
  const uint32_t started=micros();
#if BODAQS_ACQUISITION_PROFILE
  if(profileExchange)ControlPollingDiagnostics::profile(ControlPollingDiagnostics::Encode,encodingStart,started-encodingStart);
  SpiTransferTiming phases;
#endif
  auto& timing=s_diagnostics.measurementTiming;
  if(!timing.slots) measurementTimingStartUs=started;
  else {
    const uint32_t idle=started-measurementTimingEndUs;
    if(idle>timing.maxIdleUs) timing.maxIdleUs=idle;
  }
#if (defined(BODAQS_MEASUREMENT_REPLY_CAPTURE) && BODAQS_MEASUREMENT_REPLY_CAPTURE) || BODAQS_PIPELINE_TRACE
  SpiTransactionContext bus;
  auto* busContext=&bus;
#else
  SpiTransactionContext* busContext=nullptr;
#endif
  const bool transferred=transferSlot_(settings,tx,rx,BODAQS_MEASUREMENT_BYTES,25,
      BODAQS_MEASUREMENT_START_SPACING_US,BODAQS_MEASUREMENT_CS_SETUP_US,busContext
#if BODAQS_ACQUISITION_PROFILE
      ,profileExchange?&phases:nullptr
#endif
      );
#if BODAQS_ACQUISITION_PROFILE
  const uint32_t decodingStart=micros();
#if BODAQS_SPARSE_COST_PROBE
  SparseCostProbe::Frame costFrame(decodingStart);
#endif
#endif
#if BODAQS_PIPELINE_TRACE
  measurementPhysicalSequence=bus.deviceSequence;
  measurementPhysicalSequenceValid=bus.valid && bus.deviceSequenceValid;
#endif
  #if defined(BODAQS_PACKED_EXCHANGE) && BODAQS_PACKED_EXCHANGE
  ++packedUtil.exchanges;packedUtil.transferred+=transferred;
  packedUtil.exchange_us+=micros()-started;
  if(packedHasExchange){uint32_t gap=started-packedLastExchange;packedUtil.spacing_us+=gap;++packedUtil.spacing_count;
   if(gap>packedUtil.spacing_max_us)packedUtil.spacing_max_us=gap;}
  packedHasExchange=true;packedLastExchange=started;
  const bool packedWasAwaiting=packedReceiver && packedReceiver->awaiting;
#endif
  CpuOccupancy::Scope cpuDecode(CpuOccupancy::Decode);
  auto decodeResult=transferred?bodaqs_measurement_decode_result(rx,BODAQS_MEASUREMENT_BYTES,&response):BODAQS_MEASUREMENT_DECODE_OK;
  bool valid=transferred && decodeResult==BODAQS_MEASUREMENT_DECODE_OK;
#if defined(BODAQS_PACKED_EXCHANGE) && BODAQS_PACKED_EXCHANGE
  if(transferred && !memcmp(rx,"B51P",4) && packedReceiver && packedTransport && request.context==packedReceiver->context){
    BpReply decoded={};
#if BODAQS_SPARSE_COST_PROBE
    const bool shape=costFrame.decode([&](){return bp_decode(rx,sizeof rx,request.context,&decoded);});
    costFrame.decoded(shape,decoded,packedReceiver,packedTransport->recovering);
    const bool received=shape && !packedTransport->recovering && costFrame.receive([&](){return bpr_receive_decoded_notify(packedReceiver,&decoded,packedAdmit_,nullptr,packedConfirmed_,nullptr);});
#else
    const bool shape=bp_decode(rx,sizeof rx,request.context,&decoded);
#endif
    if(shape && packedTransport->recovering){valid=true;response={};response.context=request.context;}
#if BODAQS_SPARSE_COST_PROBE
    else if(shape && received){
#else
    else if(shape && bpr_receive_decoded_notify(packedReceiver,&decoded,packedAdmit_,nullptr,packedConfirmed_,nullptr)){
#endif
      valid=true;response={};response.context=request.context;
      ++packedPackets;packedItems+=decoded.count;packedReplyObserved_(decoded);
      if(packedWasAwaiting && !packedReceiver->awaiting){uint32_t delay=micros()-packedAckStarted;
       ++packedUtil.confirmations;packedUtil.confirmation_us+=delay;packedAckConfirmed_(delay);
       if(delay>packedUtil.confirmation_max_us)packedUtil.confirmation_max_us=delay;}
    }else{++packedBad;valid=false;}
    if(valid)decodeResult=BODAQS_MEASUREMENT_DECODE_OK;
  }
#endif
  if(!transferred) ++timing.transferFailedSlots;
  else if(!valid) {
    ++timing.decodeFailedSlots;
    ++timing.decodeReasons[decodeResult];
#if defined(BODAQS_MEASUREMENT_REPLY_CAPTURE) && BODAQS_MEASUREMENT_REPLY_CAPTURE
    static_assert(BODAQS_MEASUREMENT_BYTES==MeasurementReplyCapture::replyBytes,"Capture wire size mismatch");
    // Entry may still receive a legacy-width pipeline reply. Sample only after
    // the larger measurement profile has been confirmed for this recording.
    if(s_diagnostics.measurementConfirmed)
      ImuFlowDiagnostics::rejectedReply(s_diagnostics.measurementTimingContext,timing.slots+1,request.kind,rx,decodeResult,bus,tx);
#endif
  }
#if BODAQS_ACQUISITION_PROFILE
  const uint32_t decodingEnd=micros();
#if BODAQS_SPARSE_COST_PROBE
  costFrame.finish(decodingEnd);
#endif
  using namespace ControlPollingDiagnostics;
  if(profileExchange){
    profile(Decode,decodingStart,decodingEnd-decodingStart);
    profile(SpiWait,started,phases.lockWaitUs);profile(SpiPrepare,started,phases.prepareUs);
    profile(SpiTransfer,started,phases.transferUs);profile(SpiFinish,started,phases.finishUs);
  }
#endif
  measurementTimingEndUs=micros();
  const uint32_t duration=measurementTimingEndUs-started;
  ++timing.slots;timing.exchangeUs+=duration;
  timing.elapsedUs=measurementTimingEndUs-measurementTimingStartUs;
  if(duration>timing.maxExchangeUs) timing.maxExchangeUs=duration;
  if(request.kind==1 && request.body[0]>=1 && request.body[0]<=5) ++timing.polls[request.body[0]-1];
  if(!valid) ++timing.failedSlots;
  else {
    if(response.kind==0) ++timing.emptySlots;
    const uint8_t cls=bodaqs_fragment_class(response.kind);
    if(cls>=1 && cls<=5) ++timing.fragments[cls-1];
  }
  // Full-duplex responses belong to their identity, not the MOSI poll that
  // happens to carry them. Preserve a matching inspection observed on data,
  // ACK or control traffic for the next bounded inspection call.
  if(valid && s_modeInspection.token &&
     static_cast<uint32_t>(millis()-s_modeInspection.startedMs)<300 &&
     modeObservation_(response,s_modeInspection.token,s_modeInspection.context,nullptr))
    s_modeInspection.ready=true;
#if BODAQS_SPI_BOUNDARY_TRACE
  if(!valid && transferred && s_diagnostics.measurementConfirmed)
    freezeBoundary_(s_diagnostics.measurementTimingContext);
#endif
  return valid;
}



static MeasurementInbox* transportInbox_(MeasurementTransport& transport,uint8_t cls,uint8_t node) {
  if(cls<1 || cls>5 || (cls==5?node!=255:node>3)) return nullptr;
  return &transport.inboxes[cls-1][cls==5?0:node];
}
#if BODAQS_MEASUREMENT_VERSION >= 4
static void sampleCredits_(MeasurementTransport& t,uint8_t* out) {
  for(uint8_t n=0;n<4;++n) {
    if(!(t.sampleNodes&(1u<<n))) continue;
    const uint32_t base=t.sampleNext[n];
    if(base>UINT32_MAX-4) continue; // exhausted IDs cannot wrap into a fresh scope
    bodaqs_measurement_put(out+8*n,base,4);
    for(uint8_t i=0;i<4;++i) {
      const uint32_t id=base+i;
      const auto& held=sampleWindowInbox(t,n,(id-1)%4);
      if((held.state.object==id && held.state.complete) ||
         (held.state.object!=id && held.state.object && (!held.admitted || held.ackPending)))
        out[8*n+4]|=1u<<i;
    }
  }
}
#endif
static uint8_t nextDataFragment_(MeasurementInbox& inbox) {
  // All missing fragments remain missing until validated MISO supplies them.
  // A full request sweep resets this hint and retries every still-missing bit.
  const uint8_t count=(inbox.state.total+BODAQS_MEASUREMENT_BODY_BYTES-1)/BODAQS_MEASUREMENT_BODY_BYTES;
  uint8_t first=0;bool haveFirst=false;
  for(uint8_t i=0;i<count;++i) if(!(inbox.state.mask&(1UL<<i))) {
    if(!haveFirst) {first=i;haveFirst=true;}
    if(!(inbox.requestedFragments&(1UL<<i))) {inbox.requestedFragments|=1UL<<i;return i;}
  }
  inbox.requestedFragments=haveFirst?1UL<<first:0;
  return first;
}
void releaseMeasurementObject(MeasurementInbox& inbox) {
  if (!measurementAccess_()) return;
  if(inbox.ackPending && inbox.pendingAck.object!=inbox.state.object) return;
  if(inbox.state.complete) {
#if defined(BODAQS_IMU_FLOW_DIAGNOSTICS) && BODAQS_IMU_FLOW_DIAGNOSTICS
    if(!inbox.admitted) ImuFlowDiagnostics::admitted(inbox.state.cls);
#endif
    inbox.admitted=true;inbox.ackPending=true;rememberMeasurementAcknowledgement(inbox);
#if defined(BODAQS_PACKED_EXCHANGE) && BODAQS_PACKED_EXCHANGE
    packedClearConfirmed_(inbox);
#endif
  }
}

bool queueMeasurementControl(MeasurementTransport& transport,const BodaqsControlWrapped& wrapped,
                             uint32_t objectId,bool authorization) {
  if (!measurementAccess_()) return false;
  if(!measurementReady() || wrapped.node_address>3 || !objectId ||
     (transport.context && transport.context!=s_diagnostics.measurement.context)) return false;
  transport.context=s_diagnostics.measurement.context;
  auto& outbox=transport.controls[authorization?1:0][wrapped.node_address];
  uint8_t bytes[68]={};
  if(!bodaqs_control_encode_wrapped(&wrapped,bytes)) return false;
  if(outbox.state.complete) {
    if(outbox.state.object==objectId) return memcmp(outbox.bytes,bytes,64)==0;
    if(!authorization || wrapped.record.opcode!=0x25 || objectId<=outbox.state.object) return false;
  }
  memcpy(outbox.bytes,bytes,64);outbox.nextFragment=0;outbox.error=0;outbox.startedMs=millis();
  const bool sealed=bodaqs_fragment_seal(&outbox.state,outbox.bytes,68,transport.context,objectId,
      wrapped.node_address,authorization?4:3,0,64);
#if BODAQS_ORDINARY_FETCH_INTERVAL_MS
  if(sealed && !authorization) transport.ordinaryFetchSeen &= static_cast<uint8_t>(~(1u<<wrapped.node_address));
#endif
  return sealed;
}
static uint64_t loggerClockUs_() {
#if defined(ARDUINO_ARCH_ESP32)
  return static_cast<uint64_t>(esp_timer_get_time());
#else
  return micros();
#endif
}
static void measurementError_(uint8_t reason,uint8_t cls,uint8_t node,uint32_t object,const char* source) {
  ++s_diagnostics.measurementTransferErrors;
  const uint32_t bit=reason<32?(1UL<<reason):1U;
  if(!(s_diagnostics.measurementTransferErrorMask&bit)) {
    s_diagnostics.measurementTransferErrorMask|=bit;
    CANMASTER_LOGW("measurement error source=%s code=%u class=%u node=%u object=%lu\n",
      source,reason,cls,node,static_cast<unsigned long>(object));
  }
  (void)source;(void)cls;(void)node;(void)object;
}
static int unavailableTransport_(MeasurementTransport& transport) {
  transport.failed=true;s_diagnostics.measurementConfirmed=false;
  s_diagnostics.measurementUnavailable=true;return -14;
}
#if BODAQS_REQUEST_BUILD_FAST
// Selection starts with request={}; no control frame has been emitted when an
// ACK wins. Preserve that zeroed tail/index/retirement state, copying only the
// compact ACK's meaningful fields instead of constructing another bulk slot.
static void copyAckIntoZeroedRequest_(const MeasurementAcknowledgement& ack,BodaqsMeasurementSlot& request) {
  request.kind=5;request.context=ack.context;request.object=ack.object;
  request.total=ack.total;request.node=ack.node;
  memcpy(request.body,ack.body,sizeof ack.body);
}
#endif
#if BODAQS_TRANSPORT_PROFILE
// Acquisition-owner stack state only; no new publication or inbox ownership.
// Record every return, including recovery/error paths. Child fragment timing
// nests inside response time; diagnostic updates are not a CPU-time measure.
struct TransportProfileScope {
  using Stage=ControlPollingDiagnostics::Stage;
  Stage stage=ControlPollingDiagnostics::TransportRequest;
  uint32_t start=0;bool active=false;
  explicit TransportProfileScope(bool enabled):active(enabled){if(active)start=micros();}
  void enter(Stage next){
    if(!active)return;
    const uint32_t end=micros();ControlPollingDiagnostics::profile(stage,start,end-start);
    stage=next;start=micros(); // Exclude the preceding profile update from this child.
  }
  ~TransportProfileScope(){if(active){const uint32_t end=micros();ControlPollingDiagnostics::profile(stage,start,end-start);}}
};
#endif
int serviceMeasurementTransport(MeasurementTransport& transport,uint8_t cls,uint8_t node,
                                MeasurementInbox*& completed) {
  completed=nullptr;
  if (!measurementAccess_()) return -8;
  if(transport.failed) return -14;
  if(!measurementReady() || cls<1 || cls>5 || (node>3 && node!=255)) return -4;
  if(transport.context && transport.context!=s_diagnostics.measurement.context) return -4;
  transport.context=s_diagnostics.measurement.context;
#if defined(BODAQS_PACKED_EXCHANGE) && BODAQS_PACKED_EXCHANGE
  if(!packedBind_(transport))return unavailableTransport_(transport);
  struct PackedCall {PackedCall(){packedWanted=true;}~PackedCall(){packedWanted=false;}} packedCall;
#endif
#if BODAQS_TRANSPORT_PROFILE
  TransportProfileScope transportProfile(transport.timingEnabled);
#endif
  if(transport.timingEnabled && transport.bridgePending &&
     static_cast<uint32_t>(millis()-transport.bridgeStarted)>=300) {
    transport.bridgePending=false;transport.bridgeNext=millis()+100;
    transport.bridgeExpired=true;transport.bridgeReady=true;
  }
  if(transport.recovering) {
    transport.previousPollClass=0;
    for(uint8_t dataClass=0;dataClass<2;++dataClass) for(uint8_t n=0;n<4;++n)
      transport.inboxes[dataClass][n].requestedFragments=0;
    if(static_cast<uint32_t>(millis()-transport.recoveryStarted)>=300) {
      return unavailableTransport_(transport);
    }
    BodaqsMeasurementSlot query={};
#if BODAQS_REQUEST_BUILD_FAST
    BodaqsMeasurementSlot status; // Valid decode initializes it; failed exchange is never consumed.
#else
    BodaqsMeasurementSlot status={};
#endif
    query.kind=6;query.node=255;query.object=transport.recoveryToken;query.context=transport.context;
#if BODAQS_TRANSPORT_PROFILE
    transportProfile.enter(ControlPollingDiagnostics::TransportExchange);
#endif
    const bool inspected=exchangeMeasurementSlot(query,status);
#if BODAQS_TRANSPORT_PROFILE
    transportProfile.enter(ControlPollingDiagnostics::TransportResponse);
#endif
    if(!inspected) return 0;
    // A preloaded data/ACK response is not fresh evidence. It stays pinned at
    // the master until replayed after this independently correlated inspection.
    if(status.kind!=6 || status.object!=query.object || status.context!=query.context ||
       status.node!=255 || status.index || status.total) return 0;
    auto& bound=transport.recoveryBinding;
    if(bodaqs_measurement_get(status.body,8)!=bound.boot ||
       bodaqs_measurement_get(status.body+8,8)!=bound.session ||
       bodaqs_measurement_get(status.body+16,8)!=bound.recording ||
       bodaqs_measurement_get(status.body+24,8)!=bound.context ||
       status.body[32]!=2 || status.body[33] || status.body[34] || status.body[35] ||
       !(status.body[36]&1u) || (bodaqs_measurement_get(status.body+36,4)&~15ULL)) {
      return unavailableTransport_(transport);
    }
    transport.recovering=false;return 0;
  }
  // The master retains one ordered sample/evidence head per node. Continue
  // its partial object instead of spending data turns on the other class.
  if(cls<3 && node<4 && BODAQS_MEASUREMENT_VERSION<4) {
    const auto& chosen=transport.inboxes[cls-1][node].state;
    const auto& other=transport.inboxes[2-cls][node].state;
    if((!chosen.object || chosen.complete) && other.object && !other.complete) cls=3-cls;
  }
  BodaqsMeasurementSlot request={};MeasurementInbox* acked=nullptr;
#if BODAQS_REQUEST_BUILD_FAST
  BodaqsMeasurementSlot response; // Ignored on failure; successful decode zeroes/fills every field.
#else
  BodaqsMeasurementSlot response={};
#endif
  MeasurementOutbox* outgoing=nullptr;
  bool partialControl=false;
  for(int lane=1;lane>=0 && !partialControl;--lane) for(uint8_t n=0;n<4;++n) {
    const auto& retained=transport.inboxes[lane+2][n].state;
    if(transport.controls[lane][n].state.complete && retained.object && !retained.complete) {
      // Fetch and retire the predecessor before transmitting a successor.
      // The master cannot replace a pinned result, so fragment retries alone
      // would starve the missing predecessor fragment and deadlock this lane.
      cls=static_cast<uint8_t>(lane+3);node=n;partialControl=true;break;
    }
  }
  for(int lane=1;lane>=0;--lane) for(uint8_t i=0;i<4;++i) {
    uint8_t n=(transport.nextControlNode[lane]+i)%4;
    auto& candidate=transport.controls[lane][n];
    if(candidate.state.complete && static_cast<uint32_t>(millis()-candidate.startedMs)>=300) {
      candidate.state.complete=0;candidate.error=12;
      measurementError_(12,static_cast<uint8_t>(lane+3),n,candidate.state.object,"outbox_timeout");return -12;
    }
#if BODAQS_REQUEST_BUILD_FAST
    // Keep the full original timeout traversal, even after choosing outgoing.
    // Inactive/unselectable candidates need no retained-result/STOP-byte reads.
    if(!candidate.state.complete || outgoing) continue;
#endif
    const auto& retained=transport.inboxes[lane+2][n];
    // Retire the previous immutable result before sending the successor on
    // this lane. Otherwise its new fragments indefinitely suppress the RAM
    // ACK and the master correctly refuses to replace its pinned result.
    const bool retireFirst=retained.ackPending &&
        !(lane==1 && candidate.bytes[12]==0x25);
    const bool fetchFirst=retained.state.object && !retained.state.complete &&
        !(lane==1 && candidate.bytes[12]==0x25);
    if(!outgoing && candidate.state.complete && !retireFirst && !fetchFirst) {
      outgoing=&candidate;
      // Reverse the two-fragment order on each retry round (0,1,1,0).
      // A fixed 0,1 pattern can starve one fragment forever if the master's
      // saturated RX queue accepts only alternating physical slots.
      const uint8_t fragment=candidate.state.total<=BODAQS_MEASUREMENT_BODY_BYTES?0:
          (candidate.nextFragment==1 || candidate.nextFragment==2?1:0);
      (void)bodaqs_fragment_emit(&candidate.state,candidate.bytes,fragment,&request);
      candidate.nextFragment=(candidate.nextFragment+1)%4;
      transport.nextControlNode[lane]=(n+1)%4;
    }
  }
#if BODAQS_MEASUREMENT_VERSION >= 4
  // Four sample ACK attempts buy the next two data-ACK turns for evidence.
  // Otherwise a continuously full sample window can pin essential anchors.
  const uint8_t firstData=transport.sampleAckBurst>=4?2:1;
  const uint8_t priority[5]={4,3,5,firstData,static_cast<uint8_t>(3-firstData)};
#else
  const uint8_t priority[5]={4,3,5,1,2};
#endif
  for(uint8_t p:priority) {
#if BODAQS_REQUEST_BUILD_FAST
    if(outgoing || acked) break; // Candidate timeouts were already checked above.
#endif
#if BODAQS_MEASUREMENT_VERSION >= 4
    if(p==1) {
      // Retrying an ACK awaits exact retirement proof. With pipelined replies,
      // a fixed first-node/head-slot preference can indefinitely pin another
      // source. All sample slots share their class priority and bounded turns.
      for(uint8_t i=0;i<16 && !outgoing && !acked;++i) {
        const uint8_t index=(transport.nextSampleAck+i)%16;
        auto& inbox=sampleWindowInbox(transport,index%4,index/4);
        if(inbox.ackPending) {
#if BODAQS_REQUEST_BUILD_FAST
          copyAckIntoZeroedRequest_(inbox.pendingAck,request);
#else
          request=inbox.pendingAck;
#endif
          acked=&inbox;
          transport.nextSampleAck=(index+1)%16;
          if(transport.sampleAckBurst<4) ++transport.sampleAckBurst;
        }
      }
      continue;
    }
    if(p==2) {
      for(uint8_t i=0;i<4 && !outgoing && !acked;++i) {
        const uint8_t node=(transport.nextEvidenceAck+i)%4;
        auto& inbox=transport.inboxes[1][node];
        if(inbox.ackPending) {
#if BODAQS_REQUEST_BUILD_FAST
          copyAckIntoZeroedRequest_(inbox.pendingAck,request);
#else
          request=inbox.pendingAck;
#endif
          acked=&inbox;
          if(transport.evidenceAckRepeat) {
            transport.nextEvidenceAck=(node+1)%4;transport.sampleAckBurst=0;
            transport.evidenceAckRepeat=0;
          } else {
            // Repeat a pending evidence ACK on consecutive opportunities so a
            // periodic rejected SPI request cannot always erase its one turn.
            transport.nextEvidenceAck=node;transport.evidenceAckRepeat=1;
          }
        }
      }
      continue;
    }
#endif
    for(uint8_t n=0;n<(p==5?1:4);++n) {
      auto& inbox=transport.inboxes[p-1][n];
      if(!outgoing && !acked && inbox.ackPending) {
#if BODAQS_REQUEST_BUILD_FAST
        copyAckIntoZeroedRequest_(inbox.pendingAck,request);
#else
        request=inbox.pendingAck;
#endif
        acked=&inbox;
      }
    }
  }
#if BODAQS_MEASUREMENT_VERSION >= 2
  if(acked) {
    request.kind=14;request.body[2]=cls;request.body[3]=node;
#if defined(BODAQS_PACKED_EXCHANGE) && BODAQS_PACKED_EXCHANGE
    // Preserve selection/diagnostic identity, but omit the legacy fetch suffix
    // only when this exact ACK will be replaced by the packed command below.
    const bool packedAck=packedWanted && packedReceiver && packedTransport &&
        !packedTransport->recovering && packedTracksAck_(request);
    if(!packedAck) {
#endif
#if BODAQS_MEASUREMENT_VERSION >= 4
    if(cls==1) sampleCredits_(transport,request.body+16);
#endif
    auto* next=transportInbox_(transport,cls,node);
    if(next && next->state.object && !next->state.complete) {
      bodaqs_measurement_put(request.body+8,next->state.object,4);
      for(uint8_t i=0;i<BODAQS_MEASUREMENT_FRAGMENT_COUNT;++i)
        if(!(next->state.mask&(1UL<<i))) {request.body[12]=i;break;}
#if BODAQS_ACK_FETCH_FRAGMENT_SWEEP
      if(cls<3) request.body[12]=nextDataFragment_(*next);
#endif
    }
#if defined(BODAQS_PACKED_EXCHANGE) && BODAQS_PACKED_EXCHANGE
    }
#endif
  }
#endif
  if(!acked && !outgoing) {
    request.kind=1;request.context=s_diagnostics.measurement.context;request.node=node;request.body[0]=cls;
    MeasurementInbox* partial=transportInbox_(transport,cls,node);
    if(partial && partial->state.object && !partial->state.complete) {
      request.object=partial->state.object;request.node=partial->state.node;
      for(uint8_t i=0;i<BODAQS_MEASUREMENT_FRAGMENT_COUNT;++i) if(!(partial->state.mask&(1UL<<i))) {request.index=i;break;}
      // Publication can take several physical slots. Request each missing
      // fragment once before repeating gaps, rather than tracking only the
      // immediately preceding poll. This hint never marks a fragment received;
      // a new sweep retries every still-missing fragment, including a lost tail.
      if(cls<3) {
        request.index=nextDataFragment_(*partial);
      }
      if(cls==4 && node<4 && (transport.terminalNodes&(1u<<node)) && !(partial->state.mask&1u)) {
        request.object=0;request.index=0;
      }
    }
    if(cls<3 && !request.object && !(BODAQS_MEASUREMENT_VERSION>=3 && cls==1)) {
      uint8_t budgetNode=node==255?4:node;
      if(static_cast<int32_t>(millis()-transport.nextHeadPollMs[cls-1][budgetNode])<0) {
#if defined(BODAQS_IMU_FLOW_DIAGNOSTICS) && BODAQS_IMU_FLOW_DIAGNOSTICS
        if(ImuFlowDiagnostics::active) ++ImuFlowDiagnostics::live.deferred[cls-1];
#endif
        ++s_diagnostics.measurementTiming.deferrals[cls-1];return 0;
      }
      transport.nextHeadPollMs[cls-1][budgetNode]=millis()+20;
    }
  }
  if(transport.timingEnabled && !outgoing && !acked && !transport.bridgeReady &&
     ((transport.bridgePending && static_cast<int32_t>(millis()-transport.bridgeRetry)>=0) ||
      (!transport.bridgePending && static_cast<int32_t>(millis()-transport.bridgeNext)>=0))) {
    if(!transport.bridgePending && transport.bridgeToken!=UINT32_MAX) {
      ++transport.bridgeToken;transport.bridgeStarted=millis();
      transport.bridgeLower=loggerClockUs_();transport.bridgePending=true;transport.bridgeExpired=false;
    }
    if(transport.bridgePending) {
      bodaqs_bridge_request(&request,transport.context,transport.bridgeToken);
      transport.bridgeRetry=millis()+20; // normal data/ACK polls run between retries
    }
  }
#if defined(BODAQS_IMU_FLOW_DIAGNOSTICS) && BODAQS_IMU_FLOW_DIAGNOSTICS
  ImuFlowDiagnostics::request(request.kind,request.body[0],request.node,request.object,micros(),request.body[2]);
#endif
#if BODAQS_PIPELINE_TRACE
  const uint8_t traceClass=request.kind==14?request.body[2]:request.kind==1?request.body[0]:0;
  const uint8_t traceNode=request.kind==14?request.body[3]:request.node;
  const uint32_t traceObject=request.kind==14?static_cast<uint32_t>(bodaqs_measurement_get(request.body+8,4)):request.object;
  auto* traceTarget=transportInbox_(transport,traceClass,traceNode);
  const uint8_t traceMask=traceTarget && traceTarget->state.object==traceObject?static_cast<uint8_t>(traceTarget->state.mask):0;
  const uint8_t traceRequested=traceTarget?static_cast<uint8_t>(traceTarget->requestedFragments):0;
  uint8_t traceFlags=traceTarget && traceTarget->ackPending?MeasurementPipelineTrace::TargetAckPending:0;
  const uint32_t traceStarted=micros();
#endif
#if BODAQS_MEASUREMENT_VERSION >= 4
  if(request.kind==1 && request.body[0]==1) {
    request={};request.kind=15;request.context=transport.context;request.node=255;
#if defined(BODAQS_PACKED_EXCHANGE) && BODAQS_PACKED_EXCHANGE
    // Packed commands construct/project their own credits. Legacy escapes keep
    // the original builder; outgoing control, bridge and recovery are untouched.
    if(!(packedWanted && packedReceiver && packedTransport && !packedTransport->recovering))
#endif
    sampleCredits_(transport,request.body);
  }
#elif BODAQS_MEASUREMENT_VERSION == 3
  if(request.kind==1 && request.body[0]==1) {
    request={};request.context=transport.context;request.node=255;
  }
#endif
#if BODAQS_ORDINARY_FETCH_INTERVAL_MS
  const uint8_t fetchClass=request.kind==14?request.body[2]:request.kind==1?request.body[0]:0;
  const uint8_t fetchNode=request.kind==14?request.body[3]:request.node;
#if BODAQS_CONTROL_POLL_DIAGNOSTICS
  if(transport.timingEnabled){
    const uint8_t target=request.kind==15?1:request.kind==5?6:fetchClass?fetchClass:request.kind==0?0:7;
    const bool ordinary=target==3 && fetchNode<4;
    const auto* result=ordinary?&transport.inboxes[2][fetchNode]:nullptr;
    ControlPollingDiagnostics::request(target,fetchNode,
      ordinary && transport.controls[0][fetchNode].state.complete,
      result && result->state.object && !result->state.complete,
      result && result->state.object && result->state.complete && !result->admitted,
      result && result->ackPending,
      ordinary && (transport.ordinaryFetchSeen&(1u<<fetchNode)),
      ordinary?transport.ordinaryFetchMs[fetchNode]:0,millis(),micros());
  }
#endif
  if(transport.timingEnabled && fetchClass==3 && fetchNode<4) {
    transport.ordinaryFetchMs[fetchNode]=millis();transport.ordinaryFetchSeen |= 1u<<fetchNode;
  }
#endif
#if BODAQS_TRANSPORT_PROFILE
  transportProfile.enter(ControlPollingDiagnostics::TransportExchange);
#endif
  const bool exchanged=exchangeMeasurementSlot(request,response);
#if BODAQS_TRANSPORT_PROFILE
  transportProfile.enter(ControlPollingDiagnostics::TransportResponse);
#endif
#if BODAQS_PIPELINE_TRACE
  uint8_t responseMask=0;
  if(exchanged) {
    if(response.context!=transport.context) traceFlags|=MeasurementPipelineTrace::ContextMismatch;
    else if(auto* previous=transportInbox_(transport,bodaqs_fragment_class(response.kind),response.node)) {
      responseMask=static_cast<uint8_t>(previous->state.mask);
      if(response.object==previous->state.object && response.index<32 && (previous->state.mask&(1UL<<response.index)))
        traceFlags|=MeasurementPipelineTrace::KnownFragment;
      if(response.object<previous->state.object) traceFlags|=MeasurementPipelineTrace::OlderFragment;
      if(previous->state.complete && !previous->admitted) traceFlags|=MeasurementPipelineTrace::DownstreamBlocked;
    }
  }
  MeasurementPipelineTrace::record(request,exchanged?&response:nullptr,traceStarted,micros()-traceStarted,
      traceMask,traceRequested,responseMask,traceFlags,measurementPhysicalSequence,measurementPhysicalSequenceValid);
#endif
  if(!exchanged) {
#if defined(BODAQS_IMU_FLOW_DIAGNOSTICS) && BODAQS_IMU_FLOW_DIAGNOSTICS
    if(ImuFlowDiagnostics::active) ++ImuFlowDiagnostics::live.wireFailures;
#endif
    transport.previousPollClass=0;
    transport.recovering=true;transport.recoveryStarted=millis();
    transport.recoveryBinding=s_diagnostics.measurement;
    transport.recoveryToken=nextSequence_();
    if(!transport.recoveryToken) return unavailableTransport_(transport);
    return 0;
  }
  transport.previousPollClass=request.kind==1?request.body[0]:0;
  transport.previousPollNode=request.node;transport.previousPollObject=request.object;
  transport.previousPollIndex=request.index;
  if(response.context!=s_diagnostics.measurement.context) {
    transport.recovering=true;transport.recoveryStarted=millis();
    transport.recoveryBinding=s_diagnostics.measurement;transport.recoveryToken=nextSequence_();
    return 0;
  }
  const uint64_t receivedUs=loggerClockUs_();
#if defined(BODAQS_IMU_FLOW_DIAGNOSTICS) && BODAQS_IMU_FLOW_DIAGNOSTICS
  if(ImuFlowDiagnostics::active && !response.kind) ++ImuFlowDiagnostics::live.empty;
#endif
  if(response.context==transport.context && transport.bridgePending &&
     static_cast<uint32_t>(millis()-transport.bridgeStarted)<300 &&
     response.object==transport.bridgeToken && bodaqs_bridge_valid(&response,1)) {
    transport.bridgeTick=static_cast<uint32_t>(bodaqs_measurement_get(response.body+4,4));
    transport.bridgeEpoch=static_cast<uint32_t>(bodaqs_measurement_get(response.body+8,4));
    transport.bridgeUpper=receivedUs;transport.bridgeExpired=transport.bridgeEpoch==0;transport.bridgeReady=true;
    transport.bridgePending=false;transport.bridgeNext=transport.bridgeStarted+100;
  }
#if BODAQS_MEASUREMENT_VERSION >= 2
  if(response.retired) {
    auto* retired=transportInbox_(transport,response.retiredClass,response.retiredNode);
#if BODAQS_MEASUREMENT_VERSION >= 4
    if(response.retiredClass==1 && response.retiredNode<4)
      retired=&sampleWindowInbox(transport,response.retiredNode,(response.retiredObject-1)%4);
#endif
    if(retired && retired->ackPending) {
      const auto& pending=retired->pendingAck;
      if(pending.context==response.context && pending.object==response.retiredObject &&
         pending.total==response.retiredTotal &&
         bodaqs_measurement_get(pending.body+4,4)==response.retiredChecksum) {
#if defined(BODAQS_IMU_FLOW_DIAGNOSTICS) && BODAQS_IMU_FLOW_DIAGNOSTICS
        ImuFlowDiagnostics::proof(response.retiredClass,response.retiredNode,response.retiredObject,micros());
#endif
        retired->ackPending=false;
      }
    }
  }
#else
  if(acked) acked->ackPending=false;
#endif
  if(response.kind==5 && response.node<4 && (response.body[0]==3 || response.body[0]==4)) {
    auto& sent=transport.controls[response.body[0]-3][response.node];
    if(bodaqs_fragment_ack_matches(&sent.state,&response)) {
      sent.state.complete=0;++s_diagnostics.measurementControlSubmitted;
    }
    return 0;
  }
  if(response.kind==7) {
    const uint16_t stage=static_cast<uint16_t>(bodaqs_measurement_get(response.body+2,2));
    if(response.node<4 && (response.body[0]==1 || response.body[0]==2) &&
       (response.body[1]==9 || response.body[1]==14) && (stage==5 || stage==6) &&
       bodaqs_measurement_zero(response.body+8,32)) {
      if(transport.lossReady) return -8;
      transport.lossDiagnostic=response;transport.lossReady=true;
      return 0;
    }
    if(response.node<4 && (response.body[0]==3 || response.body[0]==4)) {
      auto& failed=transport.controls[response.body[0]-3][response.node];
      if(failed.state.object==response.object) {
        if(response.body[1]==8 && failed.state.complete) {
          // BUSY can mean our previous result is still pinned because its RAM
          // ACK was lost. Replay only an ACK for an actually admitted result;
          // preserve this immutable outgoing request and its original deadline.
          auto& retained=transport.inboxes[response.body[0]-1][response.node];
          if(retained.admitted && retained.state.complete && retained.state.context==transport.context) {
            rememberMeasurementAcknowledgement(retained);
            retained.ackPending=true;
#if defined(BODAQS_PACKED_EXCHANGE) && BODAQS_PACKED_EXCHANGE
            packedClearConfirmed_(retained);
#endif
          }
        } else {failed.state.complete=0;failed.error=response.body[1];}
      }
    }
    measurementError_(response.body[1],response.body[0],response.node,response.object,"master_reply");return -response.body[1];
  }
  const uint8_t responseClass=bodaqs_fragment_class(response.kind);
  if(responseClass==4 && response.node<4 && (transport.terminalNodes&(1u<<response.node)) &&
     response.index==0 && (response.body[12]==0x26 || response.body[12]==0x27)) return 0;
  // Only empty-head probing is limited to 50Hz per class/node. A validated fragment is
  // evidence of active backlog, so its successor can be selected immediately
  // after the RAM ACK instead of imposing a 20ms cap on full data batches.
  if(responseClass<3 && responseClass && response.node<4)
    transport.nextHeadPollMs[responseClass-1][response.node]=millis();
  auto* inbox=transportInbox_(transport,responseClass,response.node);
  if(!inbox){
#if defined(BODAQS_PACKED_EXCHANGE) && BODAQS_PACKED_EXCHANGE
    for(int lane=3;lane>=2;--lane)for(uint8_t n=0;n<4;++n)if(measurementObjectReady(transport.inboxes[lane][n])){
      completed=&transport.inboxes[lane][n];return 1;
    }
#endif
    return 0;
  }
#if BODAQS_MEASUREMENT_VERSION >= 4
  if(responseClass==1) {
    if(!response.object || !(transport.sampleNodes&(1u<<response.node))) return 0;
    inbox=&sampleWindowInbox(transport,response.node,(response.object-1)%4);
    if(response.object<inbox->state.object) return 0; // stale already-retired physical reply
    if(response.object!=inbox->state.object && inbox->state.object &&
       (!inbox->admitted || inbox->ackPending)) return 0; // never overwrite unretired custody
    const uint32_t base=transport.sampleNext[response.node];
    if(response.object>=base && response.object-base>=4) return 0;
  }
#endif
  if(responseClass==4 && (transport.terminalNodes&(1u<<response.node)) &&
     inbox->state.object && !inbox->state.complete && response.object>inbox->state.object) {
    // Terminal STOP supersedes the master's old renewal result, including a
    // response only partly received before STOP. That object can no longer be
    // completed; retain the last accepted cache while admitting its successor.
    auto& state=inbox->state;
    const uint32_t accepted=state.accepted, object=state.accepted_object, checksum=state.accepted_checksum;
    const uint16_t total=state.accepted_total;
    state={};state.accepted=accepted;state.accepted_object=object;
    state.accepted_checksum=checksum;state.accepted_total=total;
  }
#if BODAQS_REQUEST_BUILD_FAST
  BodaqsMeasurementSlot ack; // Read only on duplicate result2, which initializes the ACK.
#else
  BodaqsMeasurementSlot ack={};
#endif
  const uint32_t previousObject=inbox->state.object;
#if defined(BODAQS_IMU_FLOW_DIAGNOSTICS) && BODAQS_IMU_FLOW_DIAGNOSTICS
  const bool freshFragment=response.index<32 && (response.object>previousObject ||
      (previousObject==response.object && !(inbox->state.mask&(1UL<<response.index))));
#endif
#if BODAQS_TRANSPORT_PROFILE
  const uint32_t fragmentStart=transport.timingEnabled?micros():0;
#endif
  int result=bodaqs_fragment_accept(&inbox->state,inbox->bytes,sizeof(inbox->bytes),&response,1,&ack);
#if BODAQS_TRANSPORT_PROFILE
  if(transport.timingEnabled){const uint32_t end=micros();ControlPollingDiagnostics::profile(ControlPollingDiagnostics::FragmentAccept,fragmentStart,end-fragmentStart);}
#endif
#if defined(BODAQS_IMU_FLOW_DIAGNOSTICS) && BODAQS_IMU_FLOW_DIAGNOSTICS
  if(result>=0) ImuFlowDiagnostics::fragment(responseClass,freshFragment);
#endif
  if(inbox->state.object!=previousObject) inbox->requestedFragments=0;
  if(result==1) {
    inbox->admitted=false;
#if BODAQS_MEASUREMENT_VERSION == 1
    inbox->ackPending=false;
#endif
    if(measurementObjectReady(*inbox)) completed=inbox;
    else result=0; // retain the successor until predecessor retirement is confirmed
    ++s_diagnostics.measurementObjectsReceived;
  } else if(result==2) {
    ++s_diagnostics.measurementDuplicates;
    if(inbox->admitted) {inbox->ackPending=true;inbox->pendingAck=ack;
#if defined(BODAQS_PACKED_EXCHANGE) && BODAQS_PACKED_EXCHANGE
      packedClearConfirmed_(*inbox);
#endif
    }
    else if(measurementObjectReady(*inbox)) {result=1;completed=inbox;}
  } else if(result<0) {
    measurementError_(static_cast<uint8_t>(-result),responseClass,response.node,response.object,"fragment_decode");
#if BODAQS_MEASUREMENT_VERSION >= 4
    // A damaged origin-checked unit has no RAM custody and therefore no ACK.
    // Its credit stays open for bounded selective replay; other sources run.
    if(responseClass==1 && result==-3) return 0;
#endif
    if(result!=-6) return unavailableTransport_(transport);
  }
  s_diagnostics.measurementAssemblyBytes=inbox->state.complete?0:inbox->state.total;
  s_diagnostics.measurementLastClass=responseClass;s_diagnostics.measurementLastNode=response.node;
  s_diagnostics.measurementLastObject=response.object;
  return result;
}
bool acknowledgeMeasurementObject(MeasurementInbox& inbox) {
  if (!measurementAccess_()) return false;
  if(!measurementReady() || !inbox.state.complete) return false;
  BodaqsMeasurementSlot ack={}, response={};
  bodaqs_fragment_ack(&inbox.state,1,&ack);
#if BODAQS_MEASUREMENT_VERSION >= 2
  ack.kind=14;ack.body[2]=inbox.state.cls;ack.body[3]=inbox.state.node;
  const uint32_t started=millis();
  do {
    if(exchangeMeasurementSlot(ack,response) && response.context==ack.context && response.retired &&
       response.retiredClass==inbox.state.cls && response.retiredNode==inbox.state.node &&
       response.retiredObject==inbox.state.object && response.retiredTotal==inbox.state.total &&
       response.retiredChecksum==inbox.state.checksum) {inbox.ackPending=false;return true;}
  } while(static_cast<uint32_t>(millis()-started)<300);
  return false;
#else
  if(!exchangeMeasurementSlot(ack,response)) return false;
  inbox.ackPending=false; return true;
#endif
}
int pollMeasurementObject(uint8_t cls,uint8_t node,MeasurementInbox& inbox) {
  if (!measurementAccess_()) return -8;
  if(!measurementReady() || cls<1 || cls>5 || (node>3 && node!=255)) return -4;
  if(inbox.ackPending) return acknowledgeMeasurementObject(inbox)?0:-8;
  BodaqsMeasurementSlot request={},response={};
  request.kind=1;request.context=s_diagnostics.measurement.context;request.node=node;request.body[0]=cls;
  if(inbox.state.object && !inbox.state.complete) {
    request.object=inbox.state.object; request.node=inbox.state.node;
    for(uint8_t i=0;i<BODAQS_MEASUREMENT_FRAGMENT_COUNT;++i) if(!(inbox.state.mask&(1UL<<i))) {request.index=i;break;}
  }
  if(!exchangeMeasurementSlot(request,response)) return 0;
  if(response.context!=request.context) return 0;
  if(response.kind==7) {++s_diagnostics.measurementTransferErrors;return -response.body[1];}
  if(bodaqs_fragment_class(response.kind)!=cls || (node!=255 && response.node!=node)) return 0;
  BodaqsMeasurementSlot ack={};
  const int accepted=bodaqs_fragment_accept(&inbox.state,inbox.bytes,sizeof(inbox.bytes),&response,1,&ack);
  s_diagnostics.measurementAssemblyBytes=inbox.state.complete?0:inbox.state.total;
  if(accepted<0) ++s_diagnostics.measurementTransferErrors;
  if(accepted>0) {
    inbox.ackPending=true;
    if(accepted==1) ++s_diagnostics.measurementObjectsReceived;
    else ++s_diagnostics.measurementDuplicates;
    s_diagnostics.measurementLastClass=cls;s_diagnostics.measurementLastNode=response.node;
    s_diagnostics.measurementLastObject=response.object;
  }
  return accepted;
}
uint32_t nextMeasurementObjectId(uint8_t cls,uint8_t node) {
  if (!measurementAccess_()) return 0;
  static uint64_t context=0, boot=0, session=0;
  static uint32_t ids[2][4]={};
  if(!measurementReady() || cls<3 || cls>4 || node>3) return 0;
  if(context!=s_diagnostics.measurement.context || boot!=s_diagnostics.measurement.boot ||
     session!=s_diagnostics.measurement.session) {
    context=s_diagnostics.measurement.context;boot=s_diagnostics.measurement.boot;
    session=s_diagnostics.measurement.session;
    memset(ids,0,sizeof(ids));
  }
  auto& id=ids[cls-3][node];
  return id==UINT32_MAX?0:++id;
}
bool submitMeasurementControl(const BodaqsControlWrapped& wrapped,uint32_t objectId,bool authorization) {
  if (!measurementAccess_()) return false;
  if(!measurementReady()) return false;
  uint8_t data[68]={};BodaqsFragmentState tx={};
  if(!bodaqs_control_encode_wrapped(&wrapped,data) ||
     !bodaqs_fragment_seal(&tx,data,sizeof(data),s_diagnostics.measurement.context,objectId,
        wrapped.node_address,authorization?4:3,0,64)) return false;
  const uint32_t began=millis();
  do {
    for(uint8_t index=0;index<(tx.total+BODAQS_MEASUREMENT_BODY_BYTES-1)/BODAQS_MEASUREMENT_BODY_BYTES;++index) {
      BodaqsMeasurementSlot request={},response={};
      (void)bodaqs_fragment_emit(&tx,data,index,&request);
      if(exchangeMeasurementSlot(request,response) && bodaqs_fragment_ack_matches(&tx,&response)) {
        ++s_diagnostics.measurementControlSubmitted;return true;
      }
      if(response.kind==7 && response.context==tx.context && response.object==tx.object && response.node==tx.node) {
        ++s_diagnostics.measurementTransferErrors;return false;
      }
    }
  } while(static_cast<uint32_t>(millis()-began)<300);
  ++s_diagnostics.measurementTransferErrors;return false;
}
bool queryMeasurementNodeState(uint8_t node,uint32_t boot,uint32_t operation,BodaqsControlWrapped& result) {
  if (!measurementAccess_()) return false;
  static uint64_t context=0;
  static MeasurementInbox inboxes[4];
  if(!measurementReady() || node>3 || !operation || !boot) return false;
  if(context!=s_diagnostics.measurement.context) {
    context=s_diagnostics.measurement.context;
    for(auto& inbox:inboxes) inbox=MeasurementInbox{};
  }
  BodaqsControlWrapped request={};request.master_boot_id=s_diagnostics.measurement.boot;
  request.node_address=node;request.record.opcode=BODAQS_CONTROL_GET_NODE_STATE;
  request.record.endpoint=BODAQS_CONTROL_NODE_WIDE;request.record.operation=operation;
  request.record.node_boot_id=boot;
  if(!submitMeasurementControl(request,nextMeasurementObjectId(3,node))) return false;
  const uint32_t began=millis();
  do {
    int received=pollMeasurementObject(3,node,inboxes[node]);
    if(received<0) return false;
    if(received==1 && bodaqs_control_decode_wrapped(inboxes[node].bytes,64,&result)) {
      const bool match=result.master_boot_id==request.master_boot_id && result.node_address==node &&
        result.record.operation==operation && result.record.node_boot_id==boot &&
        result.record.opcode==BODAQS_CONTROL_GET_NODE_STATE && result.record.data_length==24;
      if(!acknowledgeMeasurementObject(inboxes[node])) return false;
      if(match) return true;
    }
  } while(static_cast<uint32_t>(millis()-began)<3500);
  return false;
}
static bool modeObservation_(const BodaqsMeasurementSlot& response, uint32_t token,
                             uint64_t queryContext, const BodaqsMeasurementMode* expected) {
  if (response.kind!=6 || response.node!=255 || response.index || response.total ||
      response.object!=token || response.context!=queryContext ||
      response.body[34] || response.body[35] || (bodaqs_measurement_get(response.body+36,4)&~15ULL)) return false;
  BodaqsMeasurementMode observed = s_diagnostics.measurement;
  observed.boot=bodaqs_measurement_get(response.body,8);
  observed.session=bodaqs_measurement_get(response.body+8,8);
  observed.recording=bodaqs_measurement_get(response.body+16,8);
  observed.context=bodaqs_measurement_get(response.body+24,8);
  observed.phase=response.body[32]; observed.reason=response.body[33];
  observed.flags=static_cast<uint16_t>(bodaqs_measurement_get(response.body+36,4));
  if (observed.phase>4 || (expected && !bodaqs_measurement_binding(&observed,expected))) return false;
  if ((observed.phase==2) != ((observed.flags&1U)!=0)) return false;
  if (s_diagnostics.measurementConfirmed &&
      (!bodaqs_measurement_binding(&observed,&s_diagnostics.measurement) || observed.phase!=2)) {
    s_diagnostics.measurementConfirmed=false;
    s_diagnostics.measurementUnavailable=true;
  }
  if (observed.phase==0) { observed.physical=84; observed.hz=4000000; observed.gap=1000; }
  s_diagnostics.measurementStatusValid=true;
  s_diagnostics.measurement=observed;
  return true;
}

bool inspectMeasurementMode() {
  if (!measurementAccess_()) return false;
  if (!s_nextSequence || s_nextSequence==UINT32_MAX) return false;
  if (s_diagnostics.measurementUnavailable || s_diagnostics.measurement.phase!=0) {
    // Keep one inspection identity across bounded service calls. Replacing it
    // every four slots can discard every delayed reply under RX overruns,
    // even after the master has completed its physical retirement fence.
    if(!s_modeInspection.token || s_modeInspection.boot!=s_diagnostics.measurement.boot ||
       s_modeInspection.context!=s_diagnostics.measurement.context ||
       static_cast<uint32_t>(millis()-s_modeInspection.startedMs)>=300) {
      s_modeInspection={};
      s_modeInspection.token=nextSequence_();s_modeInspection.startedMs=millis();
      s_modeInspection.boot=s_diagnostics.measurement.boot;
      s_modeInspection.context=s_diagnostics.measurement.context;
    }
    if(s_modeInspection.ready) {s_modeInspection={};return true;}
    const uint32_t token=s_modeInspection.token;
    BodaqsMeasurementSlot query = {}, response = {};
    query.kind=6; query.node=255; query.object=token; query.context=s_diagnostics.measurement.context;
    for(uint8_t attempt=0;attempt<4;++attempt) {
      (void)exchangeMeasurementSlot(query,response);
      // This includes a preloaded status from an earlier attempt using this
      // same fresh nonce. Unrelated/stale frames cannot set ready.
      if(s_modeInspection.ready) {s_modeInspection={};return true;}
    }
    return false;
  }
  s_modeInspection={};
  const uint32_t token=nextSequence_();
  if (LoggingManager::isRunning()) return false; // No legacy probing during local recording.
  CanMasterProtocol::Frame request, response;
  request.type=static_cast<CanMasterProtocol::MessageType>(10); request.sequence=token; request.payloadLength=16;
  const uint64_t nonce=freshSession_(0);
  if(!nonce) return false;
  bodaqs_measurement_put(request.payload,nonce,8);
  bodaqs_measurement_put(request.payload+8,s_diagnostics.control.master_boot_id,8);
  BodaqsMeasurementMode observed = {};
  if(!transferFrame_(request,response) || static_cast<unsigned>(response.type)!=0x8a ||
     !bodaqs_measurement_mode_decode(response.payload,response.payloadLength,&observed) ||
     observed.caller!=nonce || observed.reason || observed.phase>4 ||
     (s_diagnostics.control.master_boot_id && observed.boot!=s_diagnostics.control.master_boot_id)) return false;
  s_diagnostics.measurementStatusValid=true;
  s_diagnostics.measurement=observed;
  if(observed.phase!=0) s_diagnostics.measurementUnavailable=true;
  return true;
}

static bool transitionMode_(BodaqsMeasurementMode requested, bool exitMode) {
  s_modeInspection={};
  const uint32_t started=millis();
  if(!s_nextSequence || s_nextSequence==UINT32_MAX) return false;
  const uint32_t sequence=nextSequence_();
  if(exitMode && s_exitRecovery.pending && bodaqs_measurement_binding(&s_exitRecovery.binding,&requested))
    s_exitRecovery.sequence=sequence;
  CanMasterProtocol::Frame stage, staged;
  stage.type=static_cast<CanMasterProtocol::MessageType>(exitMode?9:8);
  stage.sequence=sequence; stage.payloadLength=64; requested.phase=exitMode?3:0;
  requested.reason=0; requested.flags=0;
  bodaqs_measurement_mode_encode(&requested,stage.payload);
  s_diagnostics.measurementConfirmed=false;
  s_diagnostics.measurementUnavailable=true;
  s_diagnostics.measurementStatusValid=false;
  s_diagnostics.measurement=requested;
  BodaqsMeasurementMode observed = {};
  if(!transferFrame_(stage,staged) || static_cast<unsigned>(staged.type)!=(exitMode?0x89U:0x88U) ||
     !bodaqs_measurement_mode_decode(staged.payload,staged.payloadLength,&observed) ||
     observed.reason || !bodaqs_measurement_binding(&observed,&requested) ||
     !bodaqs_measurement_limits(&observed) || observed.caller!=requested.caller ||
     observed.phase!=(exitMode?3:1)) return false;
  BodaqsMeasurementSlot confirm = {}, response = {};
  confirm.kind=exitMode?9:8; confirm.node=255; confirm.context=requested.context; confirm.object=sequence;
  bodaqs_measurement_confirm_body(&requested,confirm.body);
  // The first MISO value predates this request; require a later correlated reply.
  (void)exchangeMeasurementSlot(confirm,response);
  while(static_cast<uint32_t>(millis()-started)<1000) {
    if(exchangeMeasurementSlot(confirm,response) &&
       modeObservation_(response,sequence,requested.context,&requested) &&
       s_diagnostics.measurement.phase==(exitMode?0:2) && !s_diagnostics.measurement.reason) {
      s_diagnostics.measurementConfirmed=!exitMode;
      s_diagnostics.measurementUnavailable=false;
      return true;
    }
  }
  return false;
}

bool enterMeasurementMode(uint64_t recording, uint64_t context) {
  if (!measurementAccess_() || s_exitRecovery.pending) return false;
  if(!recording || !context || !present() || !s_diagnostics.controlInfoValid ||
     !s_diagnostics.authority.session || s_diagnostics.measurementUnavailable ||
     s_diagnostics.measurement.phase!=0 ||
     !(s_diagnostics.capabilities&BODAQS_MEASUREMENT_CAPABILITY)) return false;
#if defined(BODAQS_PACKED_EXCHANGE) && BODAQS_PACKED_EXCHANGE
  if(!(s_diagnostics.capabilities&0x20U) || !preparePackedBuffers())return false;
#if BODAQS_PACKED_PROGRESS
  if(!(s_diagnostics.capabilities&0x40U))return false;
#else
  if(s_diagnostics.capabilities&0x40U)return false;
#endif
  packedTransport=nullptr;packedWanted=false;
#endif
  BodaqsMeasurementMode requested = {};
  s_diagnostics.measurementTransferErrorMask=0;
  s_diagnostics.measurementTiming={};
  s_diagnostics.measurementTimingContext=context;
  requested.boot=s_diagnostics.control.master_boot_id; requested.session=s_diagnostics.authority.session;
  requested.caller=requested.session; requested.recording=recording; requested.context=context;
  requested.version=BODAQS_MEASUREMENT_VERSION; requested.maximum=1024; requested.physical=BODAQS_MEASUREMENT_BYTES; requested.hz=BODAQS_MEASUREMENT_HZ; requested.gap=25;
  const bool entered=transitionMode_(requested,false);
#if defined(BODAQS_PACKED_EXCHANGE) && BODAQS_PACKED_EXCHANGE
  if(entered){for(auto& d:packedAckCapacity)d={};packedSawRunning=false;packedAckPhase=0;packedUtil={};memset(packedLastObjects,0,sizeof packedLastObjects);packedAckStarted=packedLastExchange=0;packedHasExchange=false;packedPackets=packedItems=packedBad=packedCopies=0;return bpr_init(packedReceiver,context,true);}
#endif
  return entered;
}

bool exitMeasurementMode() {
  if (!measurementAccess_()) return false;
  if(s_exitRecovery.pending) {
    // A lost stage/confirmation reply leaves the result uncertain, not a new
    // active recording. Observe the original binding before resuming its close.
    if(!inspectMeasurementMode()) return false;
    const auto observed=s_diagnostics.measurement;
    const auto expected=s_exitRecovery.binding;
    if(!bodaqs_measurement_binding(&observed,&expected) ||
       !(observed.flags&BODAQS_MODE_FLAG_FENCED) || (observed.flags&BODAQS_MODE_FLAG_CLEANUP)) return false;
    if(observed.phase==0 && !observed.reason) {
      s_diagnostics.measurementConfirmed=false;s_diagnostics.measurementUnavailable=false;
      s_exitRecovery={};return true;
    }
    if(observed.phase==3 && !observed.reason) {
      // Retry only the confirmation of this exact staged identity. The master
      // retains its original reservation deadline; this grants no acquisition.
      BodaqsMeasurementSlot confirm={},response={};
      confirm.kind=9;confirm.node=255;confirm.context=expected.context;confirm.object=s_exitRecovery.sequence;
      bodaqs_measurement_confirm_body(&expected,confirm.body);
      for(uint8_t attempt=0;attempt<4;++attempt) {
        if(exchangeMeasurementSlot(confirm,response) &&
           modeObservation_(response,s_exitRecovery.sequence,expected.context,&expected) &&
           s_diagnostics.measurement.phase==0 && !s_diagnostics.measurement.reason) {
          s_diagnostics.measurementConfirmed=false;s_diagnostics.measurementUnavailable=false;
          s_exitRecovery={};return true;
        }
      }
      return false;
    }
    // An unreceived stage is still active; a timed-out reservation is failed.
    // Only fresh bound, quiescent/fenced evidence allows a new administrative
    // close reservation. STOP and acquisition authority remain terminal.
    if(!((observed.phase==2 && !observed.reason) || (observed.phase==4 && observed.reason==12))) return false;
    if(transitionMode_(expected,true)) {s_exitRecovery={};return true;}
    return false;
  }
  if(!s_diagnostics.measurementConfirmed) return false;
  // Node RELEASE can precede physical retirement; retain the confirmed active
  // context until a fresh observation proves both gates before staging exit.
  if(!inspectMeasurementMode() || !s_diagnostics.measurementConfirmed ||
     s_diagnostics.measurement.phase!=2 ||
     !(s_diagnostics.measurement.flags&2u) || (s_diagnostics.measurement.flags&4u)) return false;
  s_exitRecovery.binding=s_diagnostics.measurement;s_exitRecovery.pending=true;
  if(transitionMode_(s_exitRecovery.binding,true)) {s_exitRecovery={};return true;}
  return false;
}

bool measurementReady() {
  return s_diagnostics.measurementConfirmed && !s_diagnostics.measurementUnavailable &&
      s_diagnostics.measurement.phase==2 && !s_diagnostics.measurement.reason;
}

void enableControlAuthority(uint64_t session) {
  if (!measurementAccess_()) return;
  if (LoggingManager::configurationLocked() || s_recordingFence) return;
  if (session && session==s_diagnostics.authority.session) return;
  const uint32_t nextRead=s_diagnostics.authority.next_read;
  bodaqs_control_authority_client_init(&s_diagnostics.authority, session);
  if (nextRead) s_diagnostics.authority.next_read=nextRead;
  for (uint8_t address=0; address<4; ++address) {
    bodaqs_control_apply_client_invalidate(&s_diagnostics.apply,address);
    if(s_diagnostics.desiredGeneration[address]==UINT64_MAX) {
      s_diagnostics.desiredGeneration[address]=0;
      s_configurationDirty[address]=true;
    }
  }
  s_diagnostics.apply.next_transfer = 0; // Only reset in the distinct session scope.
  for (uint8_t address = 0; address < 4; ++address) {
    const auto& node = s_diagnostics.control.nodes[address];
    bodaqs_control_authority_client_node(&s_diagnostics.authority, address,
        node.node_boot_id, node.available);
  }
}

bool releaseControlAuthority(uint8_t address) {
  if (!measurementAccess_()) return false;
  if (s_diagnostics.apply.phase) return false;
  return !LoggingManager::configurationLocked() && !s_recordingFence &&
      bodaqs_control_authority_client_release(&s_diagnostics.authority, address);
}

uint8_t acquisitionLinkProfile(uint8_t address) {
 if(address>=4 || !s_diagnostics.inventoryValid) return BODAQS_CAN_LINK_UNKNOWN;
 for(const auto& peer:s_diagnostics.inventory) if(peer.nodeAddress==address && (peer.flags&1u))
  return bodaqs_can_link_from_capabilities(peer.capabilities);
 return BODAQS_CAN_LINK_UNKNOWN;
}
bool acquisitionLinkCompatible(uint8_t address) {
 return bodaqs_can_link_from_capabilities(s_diagnostics.capabilities)==BODAQS_CAN_LINK_ACQUISITION &&
        acquisitionLinkProfile(address)==BODAQS_CAN_LINK_ACQUISITION;
}
bool configurationReconciled(uint8_t address) {
  if (address >= 4 || (!s_diagnostics.desiredDisabled[address] && !s_diagnostics.desiredEnabled[address])) return false;
  const bool enabled=s_diagnostics.desiredEnabled[address];
  const uint32_t required=enabled ? 0x47f : 0x441;
  const auto& node = s_diagnostics.control.nodes[address];
  const auto& endpoint = node.endpoints[0];
  const auto& authority = s_diagnostics.authority.nodes[address];
  const uint8_t* d = endpoint.effective;
  return !s_renewSession && s_diagnostics.control.next_read_id && !s_configurationDirty[address] && authority.bound && node.available && node.valid && endpoint.current && endpoint.effective_valid &&
      authority.boot == node.node_boot_id &&
      static_cast<int32_t>(node.observed_ms - authority.confirmed_ms) >= 0 &&
      node.active_session == s_diagnostics.authority.session && d[4] == (enabled ? 2 : 1) &&
      (!enabled || (bodaqs_imu_profile_matches_effective(desiredProfile_(address),d) && d[5]==3 && !d[6])) &&
      !(bodaqs_control_get_u32(d + 16) & required) &&
      (bodaqs_control_get_u32(d + 12) & required) == required &&
      (bodaqs_control_get_u32(d + 20) & 63) == 3 &&
      bodaqs_control_get_u64(d + 144) == s_diagnostics.authority.session &&
      bodaqs_control_get_u64(d + 24) == s_diagnostics.desiredGeneration[address] &&
      (!s_diagnostics.apply.phase || s_diagnostics.apply.current.node_address != address);
}

// Observation only; configurationReconciled remains the admission authority.
uint32_t configurationReadinessBlockers(uint8_t address) {
 if(address>=4)return UINT32_C(0x80000000);
 const bool enabled=s_diagnostics.desiredEnabled[address];const uint32_t required=enabled?0x47f:0x441;
 const auto& node=s_diagnostics.control.nodes[address];const auto& endpoint=node.endpoints[0];
 const auto& authority=s_diagnostics.authority.nodes[address];const uint8_t* d=endpoint.effective;
 const bool checks[]={
  s_diagnostics.desiredDisabled[address] || enabled,
  !s_renewSession,bool(s_diagnostics.control.next_read_id),!s_configurationDirty[address],
  bool(authority.bound),bool(node.available),bool(node.valid),bool(endpoint.current),bool(endpoint.effective_valid),
  authority.boot==node.node_boot_id,static_cast<int32_t>(node.observed_ms-authority.confirmed_ms)>=0,
  node.active_session==s_diagnostics.authority.session,d[4]==(enabled?2:1),
  !enabled || (bodaqs_imu_profile_matches_effective(desiredProfile_(address),d) && d[5]==3 && !d[6]),
  !(bodaqs_control_get_u32(d+16)&required),(bodaqs_control_get_u32(d+12)&required)==required,
  (bodaqs_control_get_u32(d+20)&63)==3,bodaqs_control_get_u64(d+144)==s_diagnostics.authority.session,
  bodaqs_control_get_u64(d+24)==s_diagnostics.desiredGeneration[address],
  !s_diagnostics.apply.phase || s_diagnostics.apply.current.node_address!=address};
 uint32_t blockers=0;for(unsigned i=0;i<20;++i)if(!checks[i])blockers|=UINT32_C(1)<<i;
 return blockers;
}
const char* configurationPreparationState(uint8_t address) {
  if(address>=4 || (!desiredEnabled_(address) && !desiredDisabled_(address))) return "unconfigured";
  if(configurationReconciled(address)) return "configuration_ready";
  if(!s_diagnostics.control.nodes[address].available) return "waiting_for_node";
  if(!s_diagnostics.authority.nodes[address].bound) return "waiting_for_authority";
  if(s_diagnostics.apply.phase && s_diagnostics.apply.current.node_address==address) return "applying_configuration";
  if(!s_diagnostics.control.nodes[address].endpoints[0].current) return "verifying_configuration";
  return "configuration_not_reconciled";
}
#if defined(BODAQS_PACKED_STARTUP_DIAGNOSTICS) && BODAQS_PACKED_STARTUP_DIAGNOSTICS
void logConfigurationReadiness(){
 for(uint8_t n=0;n<4;++n){const auto& node=s_diagnostics.control.nodes[n];const auto& endpoint=node.endpoints[0];
  uint32_t blocked=configurationReadinessBlockers(n);bool ready=configurationReconciled(n);
  CANMASTER_LOGW("readiness node=%u reconciled=%u blockers=0x%05lx check_mismatch=%u apply_phase=%u apply_node=%u observed_ms=%lu authority_ms=%lu",
   unsigned(n),unsigned(ready),static_cast<unsigned long>(blocked),unsigned(ready!=(blocked==0)),
   unsigned(s_diagnostics.apply.phase),unsigned(s_diagnostics.apply.current.node_address),
   static_cast<unsigned long>(node.observed_ms),static_cast<unsigned long>(s_diagnostics.authority.nodes[n].confirmed_ms));
  (void)endpoint;(void)blocked;(void)ready;
 }
}
#endif

void scheduleConfigurationReconciliation() {
  if (!measurementAccess_()) return;
  if (LoggingManager::configurationLocked() || s_recordingFence) return;
  for(auto& dirty:s_configurationDirty) dirty=true;
}

bool recordingHandoffActive() { return s_recordingFence; }

void beginRecordingHandoff() {
  if (!measurementAccess_()) return;
  if (s_recordingFence) return;
  s_recordingFence = true;
  s_diagnostics.control.preferred_nodes=0;
  s_handoffReady = false;
  s_handoffStartedMs = millis();
}

bool recordingHandoffReady() {
  if (!measurementAccess_()) return false;
  if (!s_recordingFence) return false;
  if (s_handoffReady) return true;
  auto& apply = s_diagnostics.apply;
  bodaqs_control_apply_client_recording_fence(&apply, &s_diagnostics.authority, millis());
  const bool expired = (uint32_t)(millis() - s_handoffStartedMs) >= kRecordingHandoffMs;
  const bool owned = apply.phase || s_diagnostics.authority.pending ||
      s_diagnostics.control.pending || s_diagnostics.control.snapshot_phase;
  if (!expired && owned) return false;
  if (expired) {
    bodaqs_control_apply_client_quarantine(&apply, &s_diagnostics.authority, millis());
    bodaqs_control_authority_client_quarantine(&s_diagnostics.authority);
    s_diagnostics.control.pending = false;
    for (auto& node : s_diagnostics.control.nodes) {
      node.valid = false;
      for (auto& endpoint : node.endpoints) endpoint.current = false;
    }
    CANMASTER_LOGW("recording handoff deadline; remote outcome uncertain, local-only recording\n");
  }
  s_diagnostics.control.snapshot_phase = 0;
  s_handoffReady = true;
  return true;
}

void endRecordingHandoff() {
  if (!measurementAccess_()) return;
  s_recordingFence = false;
  s_handoffReady = false;
  s_probeRequested = true;
}

void begin(const board::BoardProfile& profile, const LoggerConfig& cfg) {
  if (s_measurementOwner) return;
  s_board = &profile;
  s_profile = profile.can_fd_master;
  s_diagnostics = Diagnostics{};
  s_modeInspection={};s_exitRecovery={};
  s_restartCleanupNeeded=false;
  s_diagnostics.mode = cfg.canMasterMode;
  s_diagnostics.profileSupported = s_profile.supported;
  s_diagnostics.irqAvailable = s_profile.irq_pin >= 0;
  s_started = true;
  s_recordingFence = false;
  s_handoffReady = false;
  s_probeRequested = false;
  s_wasLogging = LoggingManager::isRunning();
  s_lastIrqAsserted = false;
  s_haveCompletedSlot = false;
  s_lastSlotCompletedUs = 0;
  s_statusHardwareUid = 0;
  s_nextControlMs = millis();
  bodaqs_control_observer_init(&s_diagnostics.control);
  s_lastConfirmedMasterBoot = 0;
  s_lastIssuedSession = 0;
  s_renewSession = false;
  for(uint8_t address=0;address<4;++address) {
    s_nextRecoveryMs[address]=millis();
    s_nextAuthorityRetryMs[address]=millis();
  }
  s_exchangeOwner = 0;
  enableControlAuthority(freshSession_(0));

  if (!s_profile.supported) {
    s_diagnostics.state = State::Unsupported;
    return;
  }
  if (s_profile.spi_bus_index != 0 || s_profile.cs_pin < 0) {
    s_diagnostics.state = State::TransportFault;
    ++s_diagnostics.transferFailures;
    return;
  }
  // Keep a fitted but disabled peripheral deselected; an input/floating CS
  // would make "off" electrically ambiguous.
  pinMode(static_cast<uint8_t>(s_profile.cs_pin), OUTPUT);
  digitalWrite(static_cast<uint8_t>(s_profile.cs_pin), HIGH);
  if (s_profile.irq_pin >= 0) {
    pinMode(static_cast<uint8_t>(s_profile.irq_pin),
            s_profile.irq_use_internal_pullup ? INPUT_PULLUP : INPUT);
  }
  if (cfg.canMasterMode == CanMasterMode::Off) {
    s_diagnostics.state = State::Disabled;
    return;
  }
  if (!SharedSpiBus::begin(profile.spi)) {
    s_diagnostics.state = State::TransportFault;
    ++s_diagnostics.transferFailures;
    s_nextProbeMs = millis() + kAbsentProbeIntervalMs;
    return;
  }
  (void)probeNow();
}

void applyConfig(const LoggerConfig& cfg) {
  if (!measurementAccess_()) return;
  if (!s_started) return;
  const State previous = s_diagnostics.state;
  s_diagnostics.mode = cfg.canMasterMode;
  if (!s_profile.supported) {
    s_diagnostics.state = State::Unsupported;
    clearIdentity_();
  } else if (cfg.canMasterMode == CanMasterMode::Off) {
    s_diagnostics.state = State::Disabled;
    clearIdentity_();
    SensorManager::clearRemoteDiscoveryObservations();
  } else {
    (void)probeNow();
    return;
  }
  refreshInventoryIfStateChanged_(previous);
}

namespace {
// Idle-only restart recovery. This client deliberately does not share the
// configuration/apply scheduler: its only mutations are bind, fence, release.
struct RestartCleanup {
  BodaqsMeasurementMode abandoned={};
  uint64_t session=0,record=0,snapshot=0,challenge=0;
  uint32_t boot=0,read=0x80000001u,started=0,next=0,mutation=2;
  uint8_t node=0,phase=0,page=0;
  uint8_t state[128]={};
  bool pending=false,bound=false;
  BodaqsControlWrapped request={};
} cleanup;
// 0 pending, 1 complete, -1 untrusted/rejected. Every retained result is matched
// against the complete request identity; a delayed receipt cannot advance phase.
int cleanupExchange_(BodaqsControlRecord q,BodaqsControlRecord& reply) {
  const uint32_t now=millis();
  if(!cleanup.pending) {
    cleanup.request={};cleanup.request.master_boot_id=cleanup.abandoned.boot;
    cleanup.request.node_address=cleanup.node;cleanup.request.record=q;
    cleanup.started=now;cleanup.pending=true;
  }
  if(uint32_t(now-cleanup.started)>=3500) {
    // Preserve the exact uncertain mutation, particularly a possibly completed
    // BIND. A fresh challenge here would lose its idempotent result identity.
    cleanup.started=now;return -2;
  }
  auto sent=cleanup.request;
  CanMasterProtocol::Frame request,response;
  request.type=static_cast<CanMasterProtocol::MessageType>(6);
  request.sequence=nextSequence_();request.payloadLength=64;
  // Repeating the exact typed request is idempotent, including uncertain BIND.
  if(!bodaqs_control_encode_wrapped(&sent,request.payload) || !transferFrame_(request,response)) {
    return 0;
  }
  BodaqsControlWrapped observed={};
  if(!bodaqs_control_decode_wrapped(response.payload,response.payloadLength,&observed) ||
     observed.master_boot_id!=sent.master_boot_id || observed.node_address!=sent.node_address ||
     observed.record.node_boot_id!=sent.record.node_boot_id || observed.record.session!=sent.record.session ||
     observed.record.operation!=sent.record.operation || observed.record.endpoint!=sent.record.endpoint ||
     observed.record.page!=sent.record.page ||
     ((sent.record.opcode!=1 && sent.record.opcode!=0x28) && observed.record.transfer!=sent.record.transfer) ||
     (observed.record.opcode!=sent.record.opcode && observed.record.opcode!=127)) return 0;
  if(static_cast<unsigned>(response.type)==0x86) {
    if(observed.record.data_length==24 && (observed.record.data[0]==4 || observed.record.data[0]==5)) {
      cleanup.pending=false;return -1;
    }
    // The exchange caches the completed result; repeated requests retrieve it.
    return 0;
  }
  if(static_cast<unsigned>(response.type)!=0x87) return 0;
  reply=observed.record;cleanup.pending=false;
  return reply.opcode==127?-1:1;
}
void serviceRestartCleanup_() {
  if(LoggingManager::isRunning() || !measurementAccess_()) return;
  if(int32_t(millis()-cleanup.next)<0) return;
  if(!cleanup.phase) {
    cleanup={};cleanup.abandoned=s_diagnostics.measurement;
    cleanup.session=freshSession_(cleanup.abandoned.session);
    cleanup.read=esp_random();
    if(!cleanup.session || !cleanup.abandoned.boot || !cleanup.read || cleanup.read==UINT32_MAX) return;
    cleanup.phase=1;
  }
  if(cleanup.node==4) {
    // Physical master DMA retirement is independent of node results. Inspection
    // must prove it before an explicit old-context close can complete.
    if(!inspectMeasurementMode() || !bodaqs_measurement_binding(&cleanup.abandoned,&s_diagnostics.measurement) ||
       !(s_diagnostics.measurement.flags&2u) || (s_diagnostics.measurement.flags&4u)) return;
    auto close=cleanup.abandoned;close.caller=close.session;
    if(!s_diagnostics.measurement.phase || transitionMode_(close,true)) {
      cleanup={};s_probeRequested=true;
      s_restartCleanupNeeded=false;
      s_diagnostics.measurementUnavailable=false;
    }
    return;
  }
  if(cleanup.phase==1) {
    CanMasterProtocol::Frame request,response;CanMasterProtocol::DiscoveryRecord inventory;
    if(!CanMasterProtocol::encodeDiscoveryRequest(cleanup.node,0,nextSequence_(),request) ||
       !transferFrame_(request,response) || !CanMasterProtocol::decodeDiscoveryResponse(response,inventory) ||
       inventory.nodeAddress!=cleanup.node) return;
    if(!(inventory.flags&1u)) {++cleanup.node;return;}
    if((inventory.flags&6u) || !inventory.bootId || !inventory.hardwareUid) return;
    if(cleanup.boot!=inventory.bootId) cleanup.bound=false;
    cleanup.boot=inventory.bootId;cleanup.phase=2;cleanup.page=0;cleanup.snapshot=0;
  }
  BodaqsControlRecord q={},r={};q.endpoint=255;q.node_boot_id=cleanup.boot;
  q.operation=cleanup.read;q.session=0;
  switch(cleanup.phase) {
    case 2:q.opcode=0x28;q.data_length=8;break;
    case 3:q.opcode=7;q.transfer=cleanup.snapshot;q.page=cleanup.page;break;
    case 4:q.opcode=8;q.transfer=cleanup.snapshot;break;
    case 5:q.opcode=1;q.data_length=8;bodaqs_control_put_u64(q.data,cleanup.session);break;
    case 6:q.opcode=2;q.session=cleanup.session;q.operation=1;q.transfer=cleanup.challenge;break;
    case 7:case 8:
      q.opcode=cleanup.phase==7?0x2A:0x29;q.session=cleanup.session;q.operation=cleanup.mutation;
      q.data_length=24;bodaqs_control_put_u64(q.data,cleanup.record);break;
    case 9:
      q.opcode=0x14;q.session=cleanup.session;q.data_length=4;bodaqs_control_put_u32(q.data,cleanup.mutation);break;
    default:return;
  }
  const int completed=cleanupExchange_(q,r);
  if(!completed) return;
  if(completed==-2) {
    // A new master boot invalidates the old transport, even during cleanup.
    // Establish it through fresh status before replacing any typed identity.
    if(inspectMeasurementMode() && s_diagnostics.measurement.boot!=cleanup.abandoned.boot) cleanup={};
    cleanup.next=millis()+1000;return;
  }
  if(cleanup.phase!=2 && cleanup.phase!=3) ++cleanup.read;
  if(completed<0) {cleanup.next=millis()+1000;cleanup.phase=1;return;}
  switch(cleanup.phase) {
    case 2:
      if(r.data_length!=24 || r.data[0]!=5 || !r.transfer) {cleanup.phase=1;return;}
      cleanup.snapshot=r.transfer;cleanup.phase=3;break;
    case 3:
      if(r.data_length!=(cleanup.page==5?8:24)) {cleanup.phase=1;return;}
      memcpy(cleanup.state+cleanup.page*24,r.data,r.data_length);
      if(++cleanup.page==6) cleanup.phase=4;
      break;
    case 4: {
      const uint32_t flags=bodaqs_control_get_u32(cleanup.state+28);
      if(!bodaqs_control_descriptor_valid(cleanup.state,128,5,255) ||
         bodaqs_control_get_u32(cleanup.state+24)!=cleanup.boot || (flags&1u) || !(flags&64u)) {
        cleanup.phase=1;cleanup.next=millis()+1000;return;
      }
      cleanup.record=bodaqs_control_get_u64(cleanup.state+8);
      if(cleanup.record && cleanup.abandoned.recording && cleanup.record!=cleanup.abandoned.recording) {
        cleanup.phase=1;cleanup.next=millis()+1000;return;
      }
      if(!cleanup.record) cleanup.record=cleanup.abandoned.recording;
      if(!cleanup.record) {++cleanup.node;cleanup.phase=1;return;}
      cleanup.phase=cleanup.bound?7:5;break;
    }
    case 5:
      if(r.data_length!=4 || !r.transfer) {cleanup.phase=1;return;}
      cleanup.challenge=r.transfer;cleanup.phase=6;break;
    case 6:
      if(r.data_length!=24 || r.data[0]!=0) {cleanup.phase=1;return;}
      cleanup.bound=true;cleanup.mutation=2;cleanup.phase=7;break;
    case 7:case 8:
      if(r.data_length!=24) {cleanup.phase=1;return;}
      if(r.data[0]==2) {cleanup.phase=9;return;}
      if(r.data[0]!=3) {cleanup.phase=1;return;}
      if(cleanup.phase==7) {++cleanup.mutation;cleanup.phase=8;}
      else {++cleanup.node;cleanup.phase=1;cleanup.bound=false;}
      break;
    case 9:
      if(r.data_length!=24 || r.data[0]!=3) {cleanup.next=millis()+100;return;}
      if(cleanup.mutation==2) {++cleanup.mutation;cleanup.phase=8;}
      else {++cleanup.node;cleanup.phase=1;cleanup.bound=false;}
      break;
  }
}
}

bool cleanupUnavailableMeasurement() {
  if(!measurementAccess_() || LoggingManager::isRunning()) return false;
  if(!s_restartCleanupNeeded) {
    // A fresh status may reveal a confirmed master reboot. It is observational
    // only, and the cleanup client then uses current identities throughout.
    if(!inspectMeasurementMode()) return false;
    s_restartCleanupNeeded=true;cleanup={};
  }
  serviceRestartCleanup_();
  return !s_restartCleanupNeeded && !s_diagnostics.measurement.phase;
}

bool probeNow() {
  if (!measurementAccess_()) return false;
  if (!s_started || !s_profile.supported ||
      s_diagnostics.mode == CanMasterMode::Off) {
    return false;
  }
  if (s_profile.spi_bus_index != 0 || s_profile.cs_pin < 0) {
    s_diagnostics.state = State::TransportFault;
    clearIdentity_();
    return false;
  }
  if (!s_board || !SharedSpiBus::begin(s_board->spi)) {
    const State previous = s_diagnostics.state;
    s_diagnostics.state = State::TransportFault;
    clearIdentity_();
    ++s_diagnostics.transferFailures;
    s_nextProbeMs = millis() + kAbsentProbeIntervalMs;
    refreshInventoryIfStateChanged_(previous);
    return false;
  }

  const State previous = s_diagnostics.state;
  s_diagnostics.state = State::Probing;
  ++s_diagnostics.probeAttempts;
  s_diagnostics.lastProbeMs = millis();
  s_probeRequested = false;

  // MODE_INFO with expected boot zero is the only restart bootstrap discovery.
  // An active master rejects legacy identity probes; its old owner must first
  // be inspected and explicitly fenced, never resumed by this logger instance.
  if(!LoggingManager::configurationLocked() && inspectMeasurementMode() &&
     s_diagnostics.measurement.phase!=0) {
    s_diagnostics.state=State::Present;
    s_restartCleanupNeeded=true;
    return false;
  }

  CanMasterProtocol::Frame request;
  request.type = CanMasterProtocol::MessageType::ProbeRequest;
  request.sequence = nextSequence_();
  CanMasterProtocol::Frame response;
  CanMasterProtocol::Identity identity;
  if (!transferFrame_(request, response) ||
      !CanMasterProtocol::decodeIdentity(response, identity)) {
    s_diagnostics.state = State::Absent;
    clearIdentity_();
    s_nextProbeMs = millis() + kAbsentProbeIntervalMs;
    refreshInventoryIfStateChanged_(previous);
    return false;
  }

  ++s_diagnostics.probeSuccesses;
  s_diagnostics.lastSuccessMs = millis();
  const bool statusSupported =
      (identity.capabilities & CanMasterProtocol::kCapabilityStatus) != 0;
  const bool inventorySupported =
      (identity.capabilities & CanMasterProtocol::kCapabilityDiscovery) != 0;
  if ((s_statusHardwareUid != 0 &&
       s_statusHardwareUid != identity.hardwareUid) || !statusSupported) {
    clearStatus_();
    s_statusHardwareUid = 0;
  }
  if ((s_diagnostics.hardwareUid != 0 &&
       s_diagnostics.hardwareUid != identity.hardwareUid) ||
      !inventorySupported) {
    clearInventory_(true);
  }
  s_diagnostics.protocolVersion = CanMasterProtocol::kProtocolVersion;
  s_diagnostics.firmwareVersion = identity.firmwareVersion;
  s_diagnostics.capabilities = identity.capabilities;
  s_diagnostics.hardwareUid = identity.hardwareUid;
  s_diagnostics.controlSupported = (identity.capabilities & BODAQS_CONTROL_CAPABILITY) != 0;
  s_diagnostics.statusSupported = statusSupported;
  s_diagnostics.inventorySupported = inventorySupported;
  s_diagnostics.compatible =
      identity.minimumProtocolVersion <= CanMasterProtocol::kProtocolVersion &&
      identity.maximumProtocolVersion >= CanMasterProtocol::kProtocolVersion;
  s_diagnostics.state = s_diagnostics.compatible
      ? State::Present : State::Incompatible;
  if (s_diagnostics.state == State::Present &&
      s_diagnostics.statusSupported) {
    (void)refreshStatus_();
  }
  if (s_diagnostics.state == State::Present) (void)refreshControlInfo_();
  bool inventoryCommitted = false;
  if (s_diagnostics.state == State::Present &&
      s_diagnostics.inventorySupported) {
    inventoryCommitted = refreshInventory_();
  }
  s_nextProbeMs = millis() + kPresentProbeIntervalMs;
  refreshInventoryIfStateChanged_(previous, inventoryCommitted);
  CANMASTER_LOGI("probe state=%s fw=%lu capabilities=0x%08lx\n",
                 stateKey(s_diagnostics.state),
                 static_cast<unsigned long>(s_diagnostics.firmwareVersion),
                 static_cast<unsigned long>(s_diagnostics.capabilities));
  return s_diagnostics.state == State::Present;
}

void requestProbe() {
  if (!measurementAccess_()) return;
  if (!s_started || s_diagnostics.mode == CanMasterMode::Off) return;
  s_probeRequested = true;
}

void loop() {
  if (s_measurementOwner) return;
  if(s_restartCleanupNeeded) {serviceRestartCleanup_();return;}
  if (s_diagnostics.measurementUnavailable || s_diagnostics.measurement.phase!=0) {
    if(s_restartCleanupNeeded) serviceRestartCleanup_();
    return;
  }
  if (!s_started || !s_profile.supported ||
      s_diagnostics.mode == CanMasterMode::Off ||
      s_profile.spi_bus_index != 0 || s_profile.cs_pin < 0) return;
  if (s_recordingFence) {
    (void)recordingHandoffReady();
    const uint32_t now = millis();
    if (!s_handoffReady && due_(now, s_nextControlMs)) {
      s_nextControlMs = now + 100;
      serviceControl_();
      (void)recordingHandoffReady();
    }
    return;
  }
  const bool logging = LoggingManager::isRunning();
  if (s_wasLogging && !logging) s_probeRequested = true;
  s_wasLogging = logging;
  if (logging) {
    const uint32_t now = millis();
    if ((s_diagnostics.authority.pending || s_diagnostics.control.pending || s_diagnostics.apply.pending) && due_(now, s_nextControlMs)) {
      s_nextControlMs = now + 100;
      serviceControl_();
    }
    return;
  }

  const uint32_t now = millis();
  const bool irqAsserted = s_profile.irq_pin >= 0 &&
      (digitalRead(static_cast<uint8_t>(s_profile.irq_pin)) ==
       (s_profile.irq_active_low ? LOW : HIGH));
  const bool irqBecameAsserted = irqAsserted && !s_lastIrqAsserted;
  s_lastIrqAsserted = irqAsserted;
  uint8_t preparationMask=0;
#if BODAQS_PRODUCTION_RECORDING
  preparationMask=idlePreparationMask_();
  const bool preparationDiscovery=preparationMask &&
      static_cast<uint32_t>(now-s_diagnostics.lastInventoryMs)>=1000 &&
      static_cast<uint32_t>(now-s_diagnostics.lastProbeMs)>=1000;
#else
  const bool preparationDiscovery=false;
#endif
  if (s_probeRequested || irqBecameAsserted || due_(now, s_nextProbeMs) || preparationDiscovery) {
    (void)probeNow();
  }
  if (s_diagnostics.state == State::Present && due_(now, s_nextControlMs)) {
    s_nextControlMs = now + (preparationMask?5:100);
    s_diagnostics.control.preferred_nodes=preparationMask;
    serviceControl_();
    // A master reboot may have returned to legacy mode while nodes retain an
    // abandoned recording. A rejected bind is only a trigger for inspection;
    // the cleanup client still proves stopped/invalid state before takeover.
    for(const auto& peer:s_diagnostics.authority.nodes)
      if(peer.available && peer.reason==8 && !peer.bound && !s_recordingFence) {
        s_restartCleanupNeeded=true;cleanup={};break;
      }
  }
}

const Diagnostics& diagnostics() { return s_diagnostics; }

const char* stateKey(State state) {
  switch (state) {
    case State::Unsupported: return "unsupported";
    case State::Disabled: return "disabled";
    case State::Probing: return "probing";
    case State::Absent: return "absent";
    case State::Present: return "present";
    case State::Incompatible: return "incompatible";
    case State::TransportFault: return "transport_fault";
    default: return "unknown";
  }
}

const char* shortStatus() {
  switch (s_diagnostics.state) {
    case State::Present: return "M:ok";
    case State::Disabled: return "M:off";
    case State::Unsupported: return "M:n/a";
    case State::Probing: return "M:...";
    case State::Absent: return "M:--";
    case State::Incompatible:
    case State::TransportFault:
    default: return "M:!";
  }
}

const char* controlShortStatus() {
  if (!s_diagnostics.controlSupported) return "C:--";
  if (!s_diagnostics.controlInfoValid || !s_diagnostics.control.next_read_id ||
      !s_diagnostics.authority.session || s_renewSession) return "C:!";
  bool available = false;
  if (s_diagnostics.apply.phase) {
    const auto& outcome = s_diagnostics.apply.nodes[s_diagnostics.apply.current.node_address];
    return outcome.valid && outcome.kind == 6 ? "C:!" : "C:apply";
  }
  for (uint8_t a = 0; a < 4; ++a) {
    if (!s_diagnostics.control.nodes[a].available) continue;
    if (s_diagnostics.desiredGeneration[a] && !s_diagnostics.desiredDisabled[a] && !s_diagnostics.desiredEnabled[a]) return "C:unresolved";
    if (s_diagnostics.apply.nodes[a].valid && s_diagnostics.apply.nodes[a].kind != 3 && s_diagnostics.apply.nodes[a].kind != 4) return "C:!";
  }
  for (const auto& node : s_diagnostics.control.nodes) {
    if (!node.available) continue;
    available = true;
    if (node.reason) return "C:!";
    if (!node.valid) return "C:...";
    for (uint8_t endpoint = 0; endpoint < 6; ++endpoint) {
      if (!(node.endpoint_mask & (1U << endpoint))) continue;
      const auto& descriptor = node.endpoints[endpoint];
      if (!descriptor.capability_valid || !descriptor.effective_valid || !descriptor.current) return "C:...";
      if (descriptor.effective[4] == 0) return "C:unconf";
      if (descriptor.effective[4] == 3) return "C:unknown";
    }
  }
  return available ? "C:ok" : "C:--";
}

bool present() { return s_diagnostics.state == State::Present; }

bool requiredAndUnavailable() {
  return s_diagnostics.mode == CanMasterMode::Required && !present();
}

}  // namespace CanMasterManager


