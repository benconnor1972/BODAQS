#include "CanMasterManager.h"

#include <Arduino.h>
#include <SPI.h>
#include <string.h>

#include "CanMasterProtocol.h"
#include "DebugLog.h"
#include "LoggingManager.h"
#include "SensorManager.h"
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
}

void clearIdentity_() {
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

uint32_t providerCapabilities_(uint16_t endpointMask) {
  uint32_t capabilities = SENSOR_CAP_NONE;
  if ((endpointMask & (1U << 0)) != 0) {
    capabilities |= SENSOR_CAP_IMU | SENSOR_CAP_NATIVE_STREAM |
        SENSOR_CAP_SYNC_CAPTURE;
  }
  if ((endpointMask & ((1U << 1) | (1U << 2))) != 0) {
    capabilities |= SENSOR_CAP_ANALOG;
  }
  if ((endpointMask & ((1U << 3) | (1U << 4))) != 0) {
    capabilities |= SENSOR_CAP_I2C | SENSOR_CAP_NATIVE_STREAM;
  }
  return capabilities;
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
  switch (endpoint) {
    case 0:
      observation.endpoint.kind = SensorAssignment::Kind::NodeImu;
      observation.endpoint.input = 0;
      observation.capabilities = SENSOR_CAP_IMU | SENSOR_CAP_NATIVE_STREAM |
          SENSOR_CAP_SYNC_CAPTURE;
      break;
    case 1:
    case 2:
      observation.endpoint.kind = SensorAssignment::Kind::NodeAnalog;
      observation.endpoint.input = endpoint - 1;
      observation.capabilities = SENSOR_CAP_ANALOG;
      break;
    case 3:
    case 4:
      observation.endpoint.kind = SensorAssignment::Kind::NodeI2C;
      observation.endpoint.input = endpoint - 3;
      observation.capabilities = SENSOR_CAP_I2C | SENSOR_CAP_NATIVE_STREAM;
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
        providerCapabilities_(record.endpointMask);
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

void begin(const board::BoardProfile& profile, const LoggerConfig& cfg) {
  s_board = &profile;
  s_profile = profile.can_fd_master;
  s_diagnostics = Diagnostics{};
  s_diagnostics.mode = cfg.canMasterMode;
  s_diagnostics.profileSupported = s_profile.supported;
  s_diagnostics.irqAvailable = s_profile.irq_pin >= 0;
  s_started = true;
  s_probeRequested = false;
  s_wasLogging = LoggingManager::isRunning();
  s_lastIrqAsserted = false;
  s_haveCompletedSlot = false;
  s_lastSlotCompletedUs = 0;
  s_statusHardwareUid = 0;

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
  const bool logging = LoggingManager::isRunning();
  if (s_wasLogging && !logging) s_probeRequested = true;
  s_wasLogging = logging;
  if (logging) return;

  const uint32_t now = millis();
  const bool irqAsserted = s_profile.irq_pin >= 0 &&
      (digitalRead(static_cast<uint8_t>(s_profile.irq_pin)) ==
       (s_profile.irq_active_low ? LOW : HIGH));
  const bool irqBecameAsserted = irqAsserted && !s_lastIrqAsserted;
  s_lastIrqAsserted = irqAsserted;
  if (s_probeRequested || irqBecameAsserted || due_(now, s_nextProbeMs)) {
    (void)probeNow();
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

bool present() { return s_diagnostics.state == State::Present; }

bool requiredAndUnavailable() {
  return s_diagnostics.mode == CanMasterMode::Required && !present();
}

}  // namespace CanMasterManager
