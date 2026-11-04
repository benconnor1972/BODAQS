#pragma once

#include <stdint.h>

#include "BoardProfile.h"
#include "CanMasterProtocol.h"
#include "ConfigManager.h"

namespace CanMasterManager {

enum class State : uint8_t {
  Unsupported = 0,
  Disabled,
  Probing,
  Absent,
  Present,
  Incompatible,
  TransportFault,
};

struct Diagnostics {
  State state = State::Unsupported;
  CanMasterMode mode = CanMasterMode::Auto;
  bool profileSupported = false;
  bool irqAvailable = false;
  bool compatible = false;
  uint32_t probeAttempts = 0;
  uint32_t probeSuccesses = 0;
  uint32_t transferFailures = 0;
  uint32_t invalidResponses = 0;
  uint32_t statusAttempts = 0;
  uint32_t statusSuccesses = 0;
  uint32_t statusFailures = 0;
  uint32_t lastProbeMs = 0;
  uint32_t lastSuccessMs = 0;
  uint32_t lastStatusMs = 0;
  uint8_t protocolVersion = 0;
  uint32_t firmwareVersion = 0;
  uint32_t capabilities = 0;
  uint64_t hardwareUid = 0;
  bool statusSupported = false;
  bool statusValid = false;
  uint16_t statusFlags = 0;
  uint32_t masterUptimeMs = 0;
  uint32_t masterResetCause = 0;
  uint32_t masterSlotsReceived = 0;
  uint32_t masterMalformedSlots = 0;
  uint32_t masterProbesReceived = 0;
  uint32_t masterStatusRequestsReceived = 0;
  uint32_t masterSpiRecoveries = 0;
  uint32_t canRxFrames = 0;
  uint32_t canTxFrames = 0;
  uint32_t canErrorEvents = 0;
  uint16_t canRxQueueDepth = 0;
  uint16_t canRxQueueHighWater = 0;
  uint16_t spiTxQueueDepth = 0;
  uint16_t spiTxQueueHighWater = 0;
  bool inventorySupported = false;
  bool inventoryValid = false;
  uint32_t inventoryAttempts = 0;
  uint32_t inventorySuccesses = 0;
  uint32_t inventoryFailures = 0;
  uint32_t inventorySnapshotRetries = 0;
  uint32_t lastInventoryMs = 0;
  uint32_t inventoryGeneration = 0;
  uint8_t inventoryNodeCount = 0;
  uint8_t inventoryPresentCount = 0;
  uint8_t inventoryStaleCount = 0;
  uint8_t inventoryDuplicateCount = 0;
  CanMasterProtocol::DiscoveryRecord
      inventory[CanMasterProtocol::kDiscoveryNodeCount];
};

void begin(const board::BoardProfile& profile, const LoggerConfig& cfg);
void applyConfig(const LoggerConfig& cfg);
void loop();

// Performs a bounded probe immediately. Intended for boot, configuration, and
// explicit user scans; normal background probes are scheduled by loop().
bool probeNow();
void requestProbe();

const Diagnostics& diagnostics();
const char* stateKey(State state);
const char* shortStatus();
bool present();
bool requiredAndUnavailable();

}  // namespace CanMasterManager
