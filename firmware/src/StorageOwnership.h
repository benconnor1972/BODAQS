#pragma once
#include <atomic>
#include <cstdint>
#include <utility>

// Public admission boundary. An admitted file/operation retains its lease until
// it closes; draining rejects new work but lets existing transfers finish.
class StorageOwnership {
public:
  enum class State : uint8_t { Local, Draining, Unmounting, External, Reclaiming, Error };

  class Lease {
  public:
    Lease() = default;
    Lease(const Lease&) = delete;
    Lease& operator=(const Lease&) = delete;
    Lease(Lease&& other) noexcept : owner_(other.owner_) { other.owner_ = nullptr; }
    ~Lease() { if (owner_) --owner_->localUsers_; }
    explicit operator bool() const { return owner_ != nullptr; }
  private:
    friend class StorageOwnership;
    explicit Lease(StorageOwnership* owner) : owner_(owner) {}
    StorageOwnership* owner_ = nullptr;
  };

  Lease acquireLocal() {
    if (state() != State::Local) return {};
    ++localUsers_;
    // Close the race with a handoff request between admission and increment.
    if (state() == State::Local) return Lease(this);
    --localUsers_;
    return {};
  }
  bool requestExternal() { return transition(State::Local, State::Draining); }
  bool cancelExternal() { return transition(State::Draining, State::Local); }
  bool beginExternal() {
    return localUsers_ == 0 && transition(State::Draining, State::Unmounting);
  }
  void externalReady() { transition(State::Unmounting, State::External); }
  bool beginReclaim() {
    return transition(State::External, State::Reclaiming) || transition(State::Error, State::Reclaiming);
  }
  void reclaimComplete(bool succeeded) {
    transition(State::Reclaiming, succeeded ? State::Local : State::Error);
  }
  State state() const { return state_.load(); }
  bool localAvailable() const { return state() == State::Local; }

private:
  bool transition(State expected, State desired) {
    return state_.compare_exchange_strong(expected, desired);
  }
  std::atomic<State> state_{State::Local};
  std::atomic<uint32_t> localUsers_{0};
};
