#include "CanMasterManager.h"

#include <Arduino.h>
#include <SPI.h>
#include <esp_system.h>
#include <string.h>

#include "CanMasterProtocol.h"
#include "CanMasterDiscovery.h"
#include "DebugLog.h"
#include "LoggingManager.h"
#include "SensorManager.h"
#include "SensorAssignment.h"
#include "Lsm6dso32xConfig.h"
#include "SharedSpiBus.h"

#define CANMASTER_LOGI(...) LOGI_TAG("CANMASTER", __VA_ARGS__)
#define CANMASTER_LOGW(...) LOGW_TAG("CANMASTER", __VA_ARGS__)

namespace {

constexpr uint32_t kAbsentProbeIntervalMs = 5000;
constexpr uint32_t kPresentProbeIntervalMs = 30000;
constexpr uint8_t kFetchAttempts = 3;
constexpr uint8_t kInventorySnapshotAttempts = 3;
constexpr uint32_t kSpiLockTimeoutMs = 10;
constexpr uint32_t kInterSlotGuardUs = 1000;
constexpr uint32_t kNodeStatusFlagErrorPassive = 1UL << 2;
constexpr uint32_t kNodeStatusFlagClockFault = 1UL << 8;

const board::BoardProfile* s_board = nullptr;
board::CanFdMasterProfile s_profile;
CanMasterManager::Diagnostics s_diagnostics;
uint32_t s_nextSequence = 1;
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

void scheduleDisabled_() {
  if (LoggingManager::configurationLocked() || s_recordingFence) return;
  for (uint8_t address = 0; address < 4; ++address) {
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
    if(enabled) { descriptor[4]=descriptor[8]=descriptor[10]=1; }
    if (bodaqs_control_apply_client_start(&s_diagnostics.apply, &s_diagnostics.authority,
        s_diagnostics.control.master_boot_id, address, generation,
        bodaqs_control_get_u64(endpoint.effective + 32), descriptor, millis())) {
      s_nextRecoveryMs[address]=millis()+30000;
      return;
    }
  }
}

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
    const SPISettings& settings, const uint8_t* tx, uint8_t* rx) {
  if (s_haveCompletedSlot) {
    const uint32_t elapsedUs = micros() - s_lastSlotCompletedUs;
    if (elapsedUs < kInterSlotGuardUs) {
      delayMicroseconds(kInterSlotGuardUs - elapsedUs);
    }
  }
  if (!SharedSpiBus::transfer(
          s_profile.cs_pin, settings, tx, rx,
          CanMasterProtocol::kSlotBytes, kSpiLockTimeoutMs)) {
    return false;
  }
  s_lastSlotCompletedUs = micros();
  s_haveCompletedSlot = true;
  return true;
}

bool transferFrame_(
    const CanMasterProtocol::Frame& request,
    CanMasterProtocol::Frame& response) {
  uint8_t tx[CanMasterProtocol::kSlotBytes];
  uint8_t rx[CanMasterProtocol::kSlotBytes];
  if (!CanMasterProtocol::encodeSlot(request, tx, sizeof(tx))) return false;
  const SPISettings settings(
      s_profile.spi_hz ? s_profile.spi_hz : 1000000UL,
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
      auto& node=s_diagnostics.control.nodes[s_diagnostics.control.current.node_address];
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
  if (!authorityRequest && !applyRequest && s_recordingFence && !s_diagnostics.control.pending) return;
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

void enableControlAuthority(uint64_t session) {
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
  if (s_diagnostics.apply.phase) return false;
  return !LoggingManager::configurationLocked() && !s_recordingFence &&
      bodaqs_control_authority_client_release(&s_diagnostics.authority, address);
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
      (!enabled || (d[40]==1 && !d[41] && d[42]==1 && !d[43] && d[5]==3 && !d[6])) &&
      !(bodaqs_control_get_u32(d + 16) & required) &&
      (bodaqs_control_get_u32(d + 12) & required) == required &&
      (bodaqs_control_get_u32(d + 20) & 63) == 3 &&
      bodaqs_control_get_u64(d + 144) == s_diagnostics.authority.session &&
      bodaqs_control_get_u64(d + 24) == s_diagnostics.desiredGeneration[address] &&
      (!s_diagnostics.apply.phase || s_diagnostics.apply.current.node_address != address);
}

void scheduleConfigurationReconciliation() {
  if (LoggingManager::configurationLocked() || s_recordingFence) return;
  for(auto& dirty:s_configurationDirty) dirty=true;
}

bool recordingHandoffActive() { return s_recordingFence; }

void beginRecordingHandoff() {
  if (s_recordingFence) return;
  s_recordingFence = true;
  s_handoffReady = false;
  s_handoffStartedMs = millis();
}

bool recordingHandoffReady() {
  if (!s_recordingFence) return false;
  if (s_handoffReady) return true;
  auto& apply = s_diagnostics.apply;
  bodaqs_control_apply_client_recording_fence(&apply, &s_diagnostics.authority, millis());
  const bool expired = (uint32_t)(millis() - s_handoffStartedMs) >= kRecordingHandoffMs;
  const bool owned = apply.phase || s_diagnostics.authority.pending || s_diagnostics.control.pending;
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
  s_recordingFence = false;
  s_handoffReady = false;
  s_probeRequested = true;
}

void begin(const board::BoardProfile& profile, const LoggerConfig& cfg) {
  s_board = &profile;
  s_profile = profile.can_fd_master;
  s_diagnostics = Diagnostics{};
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

bool probeNow() {
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
  if (!s_started || s_diagnostics.mode == CanMasterMode::Off) return;
  s_probeRequested = true;
}

void loop() {
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
  if (s_probeRequested || irqBecameAsserted || due_(now, s_nextProbeMs)) {
    (void)probeNow();
  }
  if (s_diagnostics.state == State::Present && due_(now, s_nextControlMs)) {
    s_nextControlMs = now + 100;
    serviceControl_();
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
