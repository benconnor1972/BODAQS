#pragma once

#include <stddef.h>
#include <stdint.h>

#include "SensorAssignment.h"
#include "SensorTypes.h"

enum class SensorIssueSeverity : uint8_t {
  Info = 0,
  Warning,
  Error,
  Critical,
};

enum class SensorIssueScope : uint8_t {
  Global = 0,
  Provider,
  Endpoint,
  Sensor,
};

enum class SensorIssueImpact : uint8_t {
  None = 0,
  ExcludeSensor,
  ExcludeProvider,
  BlockSession,
};

enum class SensorIssueCode : uint16_t {
  None = 0,
  DuplicateSensorName,
  DuplicateSensorIdentity,
  EndpointConflict,
  ReservedEndpoint,
  UnknownSensorType,
  InvalidEndpoint,
  ProviderAbsent,
  SensorAbsent,
  CapabilityMismatch,
  InitializationFailed,
  RuntimeConfigurationDiffers,
  DataStale,
  ProviderReset,
  ProviderReplaced,
  QueueLoss,
  BusOff,
  PowerFault,
};

struct SensorDiagnosticIssue {
  SensorIssueCode code = SensorIssueCode::None;
  SensorIssueSeverity severity = SensorIssueSeverity::Info;
  SensorIssueScope scope = SensorIssueScope::Sensor;
  SensorIssueImpact impact = SensorIssueImpact::None;
  uint8_t sensorIndex = 0xFF;
  uint8_t relatedSensorIndex = 0xFF;
  SensorAssignment endpoint;
  int32_t evidenceA = 0;
  int32_t evidenceB = 0;
};

class SensorDiagnosticList {
public:
  static constexpr uint8_t CAPACITY = 64;

  void clear();
  bool add(const SensorDiagnosticIssue& issue);
  uint8_t count() const { return count_; }
  bool truncated() const { return truncated_; }
  const SensorDiagnosticIssue* at(uint8_t index) const;
  bool excludesSensor(uint8_t sensorIndex) const;
  bool blocksSession() const;
  SensorIssueSeverity highestSeverity() const;

private:
  SensorDiagnosticIssue issues_[CAPACITY];
  uint8_t count_ = 0;
  bool truncated_ = false;
};

const char* sensorIssueCodeKey(SensorIssueCode code);

