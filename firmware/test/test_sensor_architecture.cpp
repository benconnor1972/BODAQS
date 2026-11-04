#include <cstdio>
#include <cstring>

#include "SensorAssignment.h"
#include "SensorDiagnostics.h"
#include "SensorInventory.h"
#include "SensorParams.h"
#include "SensorTypes.h"

namespace {
SensorSpec makeSpec(ParamStore& store) {
  SensorSpec spec;
  spec.params.bind(&store);
  return spec;
}
}

int runSensorArchitectureTests() {
  int passed = 0;
  int failed = 0;
  auto check = [&](bool condition, const char* description) {
    if (condition) ++passed;
    else {
      std::printf("    FAIL: test_sensor_architecture: %s\n", description);
      ++failed;
    }
  };

  check(MAX_SENSORS == 32, "configured sensor limit is 32");
  check(sizeof(ParamStore) <= 1440, "packed parameter store remains bounded");

  ParamStore store;
  check(store.set("i2c_bus", "1") && store.set("i2c_addr", "54"),
        "packed store accepts parameters");
  check(std::strcmp(store.get("I2C_ADDR"), "54") == 0,
        "packed store lookup is case insensitive");
  check(store.set("i2c_addr", "55") && std::strcmp(store.get("i2c_addr"), "55") == 0,
        "packed store replaces values");
  ParamStore copied = store;
  store.set("i2c_addr", "56");
  check(std::strcmp(copied.get("i2c_addr"), "55") == 0,
        "packed store copies own their text");
  check(copied.remove("i2c_bus") && copied.get("i2c_bus") == nullptr,
        "packed store removes and compacts entries");

  board::BoardProfile board;
  board.analog.count = 1;
  board.analog.inputs[0].source = board::AnalogSourceType::InternalGpio;
  board.analog.inputs[0].pin = 9;

  ParamStore localStore;
  SensorSpec local = makeSpec(localStore);
  local.type = SensorType::AnalogPot;
  local.params.setInt("ain", 0);
  const auto localAssignment = sensorAssignment(local, &board);
  check(localAssignment.provider.kind == SensorProviderKind::Local &&
            localAssignment.kind == SensorAssignment::Kind::Gpio &&
            localAssignment.input == 9,
        "legacy local assignment maps through the board profile");

  ParamStore remoteStore;
  SensorSpec remote = makeSpec(remoteStore);
  remote.params.set("provider", String("can:2"));
  remote.params.set("endpoint", String("i2c:1"));
  const auto remoteAssignment = sensorAssignment(remote, &board);
  check(remoteAssignment.provider.kind == SensorProviderKind::CanNode &&
            remoteAssignment.provider.index == 2 &&
            remoteAssignment.kind == SensorAssignment::Kind::NodeI2C &&
            remoteAssignment.input == 1,
        "remote assignment uses strapped node and single-sensor I2C port");

  ParamStore duplicateStore;
  SensorSpec duplicate = makeSpec(duplicateStore);
  duplicate.params.set("provider", String("can2"));
  duplicate.params.set("endpoint", String("i2c:1"));
  check(assignmentsConflict(remoteAssignment, sensorAssignment(duplicate, &board)),
        "same remote port conflicts");
  duplicate.params.set("endpoint", String("i2c:0"));
  check(!assignmentsConflict(remoteAssignment, sensorAssignment(duplicate, &board)),
        "different remote ports do not conflict");
  duplicate.params.set("provider", String("can:3"));
  duplicate.params.set("endpoint", String("i2c:1"));
  check(!assignmentsConflict(remoteAssignment, sensorAssignment(duplicate, &board)),
        "same port on another strapped node does not conflict");
  duplicate.params.set("provider", String("can:9"));
  check(sensorAssignment(duplicate, &board).kind == SensorAssignment::Kind::None,
        "invalid provider text cannot fall back to local hardware");

  SensorInventory inventory;
  SensorProviderObservation provider;
  provider.id = remoteAssignment.provider;
  provider.present = provider.healthy = true;
  provider.hardwareUid = 0x1234;
  provider.capabilities = SENSOR_CAP_I2C | SENSOR_CAP_SYNC_CAPTURE;
  check(inventory.observeProvider(provider), "inventory accepts a CAN provider");
  SensorEndpointObservation endpoint;
  endpoint.endpoint = remoteAssignment;
  endpoint.present = endpoint.healthy = true;
  endpoint.capabilities = SENSOR_CAP_I2C;
  check(inventory.observeEndpoint(endpoint), "inventory accepts a remote endpoint");
  check(inventory.provider(remoteAssignment.provider)->hardwareUid == 0x1234 &&
            inventory.endpoint(remoteAssignment)->healthy,
        "inventory looks up provider and endpoint observations");
  check(inventory.providerAt(0) != nullptr && inventory.endpointAt(0) != nullptr &&
            inventory.providerAt(1) == nullptr && inventory.endpointAt(1) == nullptr,
        "inventory exposes bounded observations for discovery summaries");
  provider.hardwareUid = 0x5678;
  check(inventory.observeProvider(provider) && inventory.providerCount() == 1 &&
            inventory.provider(remoteAssignment.provider)->hardwareUid == 0x5678,
        "replacement hardware updates the strapped provider rather than adding one");

  SensorDiagnosticList issues;
  SensorDiagnosticIssue issue;
  issue.code = SensorIssueCode::EndpointConflict;
  issue.severity = SensorIssueSeverity::Error;
  issue.impact = SensorIssueImpact::ExcludeSensor;
  issue.sensorIndex = 3;
  issue.relatedSensorIndex = 7;
  issue.endpoint = remoteAssignment;
  check(issues.add(issue) && issues.excludesSensor(3) && issues.excludesSensor(7),
        "structured issue excludes both endpoint claimants");
  check(!issues.blocksSession() && issues.highestSeverity() == SensorIssueSeverity::Error,
        "sensor issue does not become a global block");
  issue.code = SensorIssueCode::PowerFault;
  issue.impact = SensorIssueImpact::BlockSession;
  issue.scope = SensorIssueScope::Global;
  issue.severity = SensorIssueSeverity::Critical;
  check(issues.add(issue) && issues.blocksSession() &&
            issues.highestSeverity() == SensorIssueSeverity::Critical,
        "global issue can block the session explicitly");
  check(std::strcmp(sensorIssueCodeKey(SensorIssueCode::EndpointConflict),
                    "endpoint_conflict") == 0,
        "issue codes have stable external keys");
  inventory.clear();
  check(inventory.providerCount() == 0 && inventory.endpointCount() == 0,
        "a new discovery pass replaces the previous inventory");

  std::printf("Sensor architecture: %d passed, %d failed\n", passed, failed);
  return failed;
}
