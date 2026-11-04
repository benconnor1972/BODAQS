#include "SensorInventory.h"

void SensorInventory::clear() {
  providerCount_ = 0;
  endpointCount_ = 0;
}

bool SensorInventory::observeProvider(const SensorProviderObservation& observation) {
  for (uint8_t i = 0; i < providerCount_; ++i) {
    if (providers_[i].id == observation.id) {
      providers_[i] = observation;
      return true;
    }
  }
  if (providerCount_ >= MAX_PROVIDERS) return false;
  providers_[providerCount_++] = observation;
  return true;
}

bool SensorInventory::observeEndpoint(const SensorEndpointObservation& observation) {
  if (observation.endpoint.kind == SensorAssignment::Kind::None) return false;
  for (uint8_t i = 0; i < endpointCount_; ++i) {
    if (endpoints_[i].endpoint == observation.endpoint) {
      endpoints_[i] = observation;
      return true;
    }
  }
  if (endpointCount_ >= MAX_ENDPOINTS) return false;
  endpoints_[endpointCount_++] = observation;
  return true;
}

const SensorProviderObservation* SensorInventory::provider(const SensorProviderId& id) const {
  for (uint8_t i = 0; i < providerCount_; ++i) {
    if (providers_[i].id == id) return &providers_[i];
  }
  return nullptr;
}

const SensorEndpointObservation* SensorInventory::endpoint(const SensorAssignment& id) const {
  for (uint8_t i = 0; i < endpointCount_; ++i) {
    if (endpoints_[i].endpoint == id) return &endpoints_[i];
  }
  return nullptr;
}

const SensorProviderObservation* SensorInventory::providerAt(uint8_t index) const {
  return index < providerCount_ ? &providers_[index] : nullptr;
}

const SensorEndpointObservation* SensorInventory::endpointAt(uint8_t index) const {
  return index < endpointCount_ ? &endpoints_[index] : nullptr;
}

