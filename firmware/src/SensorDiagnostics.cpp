#include "SensorDiagnostics.h"

void SensorDiagnosticList::clear() {
  count_ = 0;
  truncated_ = false;
}

bool SensorDiagnosticList::add(const SensorDiagnosticIssue& issue) {
  if (issue.code == SensorIssueCode::None) return false;
  if (count_ >= CAPACITY) {
    truncated_ = true;
    return false;
  }
  issues_[count_++] = issue;
  return true;
}

const SensorDiagnosticIssue* SensorDiagnosticList::at(uint8_t index) const {
  return index < count_ ? &issues_[index] : nullptr;
}

bool SensorDiagnosticList::excludesSensor(uint8_t sensorIndex) const {
  for (uint8_t i = 0; i < count_; ++i) {
    const auto& issue = issues_[i];
    if (issue.sensorIndex == sensorIndex &&
        issue.impact == SensorIssueImpact::ExcludeSensor) return true;
    if (issue.relatedSensorIndex == sensorIndex &&
        issue.impact == SensorIssueImpact::ExcludeSensor) return true;
  }
  return false;
}

bool SensorDiagnosticList::blocksSession() const {
  for (uint8_t i = 0; i < count_; ++i) {
    if (issues_[i].impact == SensorIssueImpact::BlockSession) return true;
  }
  return false;
}

SensorIssueSeverity SensorDiagnosticList::highestSeverity() const {
  SensorIssueSeverity result = SensorIssueSeverity::Info;
  for (uint8_t i = 0; i < count_; ++i) {
    if ((uint8_t)issues_[i].severity > (uint8_t)result) result = issues_[i].severity;
  }
  return result;
}

const char* sensorIssueCodeKey(SensorIssueCode code) {
  switch (code) {
    case SensorIssueCode::DuplicateSensorName: return "duplicate_sensor_name";
    case SensorIssueCode::DuplicateSensorIdentity: return "duplicate_sensor_identity";
    case SensorIssueCode::EndpointConflict: return "endpoint_conflict";
    case SensorIssueCode::ReservedEndpoint: return "reserved_endpoint";
    case SensorIssueCode::UnknownSensorType: return "unknown_sensor_type";
    case SensorIssueCode::InvalidEndpoint: return "invalid_endpoint";
    case SensorIssueCode::ProviderAbsent: return "provider_absent";
    case SensorIssueCode::SensorAbsent: return "sensor_absent";
    case SensorIssueCode::CapabilityMismatch: return "capability_mismatch";
    case SensorIssueCode::InitializationFailed: return "initialization_failed";
    case SensorIssueCode::RuntimeConfigurationDiffers: return "runtime_configuration_differs";
    case SensorIssueCode::DataStale: return "data_stale";
    case SensorIssueCode::ProviderReset: return "provider_reset";
    case SensorIssueCode::ProviderReplaced: return "provider_replaced";
    case SensorIssueCode::QueueLoss: return "queue_loss";
    case SensorIssueCode::BusOff: return "bus_off";
    case SensorIssueCode::PowerFault: return "power_fault";
    case SensorIssueCode::None:
    default: return "none";
  }
}

