#include "UsbUploadSession.h"

namespace {
struct Labels { const char* key; const char* full; const char* shortText; };
constexpr Labels labels[] = {
  {"normal", "Ready", "Ready"}, {"upload", "Upload mode", "Upload mode"},
  {"waiting", "Waiting for Wi-Fi transfer", "Waiting Wi-Fi"},
  {"shared", "USB drive active", "USB active"},
  {"disconnecting", "Disconnecting USB...", "Disconnecting USB..."},
  {"reclaiming", "Reclaiming SD...", "Reclaiming SD..."},
  {"ejected", "USB ejected", "USB ejected"},
  {"error", "Storage error", "Storage error"},
};
}

bool UsbUploadSession::enter(bool logging) {
  if (logging) return false;
  if (active_) return true;
  active_ = true;
  exit_ = suppressed_ = retry_ = false;
  reconnectPending_ = false;
  error_ = nullptr;
  state_ = State::Upload;
  return true;
}

void UsbUploadSession::requestExit(uint32_t now) {
  if (!active_ || exit_) return;
  exit_ = true;
  exitRequestedMs_ = now;
}

bool UsbUploadSession::cancelExit() {
  if (!exit_ || state_ == State::Reclaiming) return false;
  exit_ = false;
  if (state_ == State::Disconnecting) state_ = State::Shared;
  return true;
}

void UsbUploadSession::poll(const Inputs& input, uint32_t now) {
  const bool newSession = input.connectionEpoch != connectionEpoch_;
  connectionEpoch_ = input.connectionEpoch;
  const bool reconnected = input.connected && (!wasConnected_ || newSession);
  wasConnected_ = input.connected;
  if (!active_) return;
  if (newSession && (state_ == State::Shared || state_ == State::Disconnecting || state_ == State::Waiting)) {
    reconnectPending_ = true;
  }
  if (reconnected) { suppressed_ = false; retry_ = true; error_ = nullptr; }
  if (input.ejected) suppressed_ = true;
  if (input.ioFailed) { suppressed_ = true; error_ = "USB storage error"; }
  if (!input.present) { suppressed_ = true; error_ = "SD removed"; }
  // A deliberate mode exit after reinsertion is itself a reclaim retry.
  if (exit_ && state_ == State::Error && input.present) error_ = nullptr;
  if (retry_) {
    retry_ = false;
    if (!backend_.localReady() && state_ == State::Error && !backend_.reclaim()) {
      error_ = input.present ? "SD remount failed" : "SD removed";
      return;
    }
    if (state_ == State::Error) { error_ = nullptr; state_ = State::Ejected; }
  }
  if (state_ == State::Error && !exit_) return;

  const bool exported = state_ == State::Shared || state_ == State::Disconnecting;
  const bool shouldReclaim = exit_ || !input.connected || suppressed_ || reconnectPending_ || state_ == State::Reclaiming;
  if (shouldReclaim) {
    const bool quietExit = exported && exit_ && !reconnectPending_ && input.connected && input.present && !input.ejected && !error_;
    if (quietExit && (uint32_t(now - exitRequestedMs_) < 3000 ||
                      input.busy || uint32_t(now - input.lastIoMs) < 1000)) {
      state_ = State::Disconnecting;
      return;
    }
    backend_.cancelStorage();
    if (!backend_.withdraw(quietExit)) {
      state_ = quietExit ? State::Disconnecting : State::Reclaiming;
      return;
    }
    state_ = State::Reclaiming;
    if (!backend_.reclaim() || !input.present || error_) {
      if (!error_) error_ = "SD remount failed";
      state_ = State::Error;
      suppressed_ = true;
      exit_ = false;
      return;
    }
    if (exit_) {
      active_ = exit_ = false;
      state_ = State::Normal;
    } else {
      state_ = suppressed_ ? State::Ejected : State::Upload;
    }
    reconnectPending_ = false;
    return;
  }
  if (exported) return;
  if (state_ == State::Waiting) {
    if (!backend_.storageGranted()) return;
    const auto result = backend_.expose();
    if (result == ExposeResult::Ready) state_ = State::Shared;
    else if (result == ExposeResult::LinkChanged) { reconnectPending_ = true; state_ = State::Reclaiming; }
    else { error_ = "USB export failed"; suppressed_ = true; state_ = State::Reclaiming; }
    return;
  }
  if (!backend_.localReady() || !backend_.requestStorage()) {
    state_ = State::Error;
    suppressed_ = true;
    error_ = "SD unavailable";
    return;
  }
  state_ = State::Waiting;
}

const char* UsbUploadSession::label() const {
  return state_ == State::Error && error_ ? error_ : labels[unsigned(state_)].full;
}
const char* UsbUploadSession::stateKey() const { return labels[unsigned(state_)].key; }
const char* UsbUploadSession::shortLabel() const {
  return state_ == State::Error ? label() : labels[unsigned(state_)].shortText;
}
