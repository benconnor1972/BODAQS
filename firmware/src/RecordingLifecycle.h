#pragma once
#include <atomic>
#include <stdint.h>

// Transitions belong to the control-loop task. Producers only publish STOP
// requests; they never retire sensors or storage from their own task.
class RecordingLifecycle {
public:
  enum class State : uint8_t {
    Ready, Preparing, Recording, Stopping, Finalizing, Completed, Failed, Uncertain
  };
  State state() const { return state_.load(std::memory_order_acquire); }
  void publish(State next) { state_.store(next, std::memory_order_release); }
  bool busy() const {
    const auto current = state();
    return current == State::Preparing || current == State::Recording ||
        current == State::Stopping || current == State::Finalizing ||
        current == State::Uncertain;
  }
  void requestStop(uint8_t reason) {
    if (reason < 32) pendingStops_.fetch_or(uint32_t{1} << reason, std::memory_order_release);
  }
  uint32_t takeStopRequests() { return pendingStops_.exchange(0, std::memory_order_acq_rel); }
  static const char* name(State state) {
    switch (state) {
      case State::Ready: return "ready";
      case State::Preparing: return "preparing";
      case State::Recording: return "recording";
      case State::Stopping: return "stopping";
      case State::Finalizing: return "finalizing";
      case State::Completed: return "completed";
      case State::Failed: return "failed";
      case State::Uncertain: return "uncertain";
    }
    return "uncertain";
  }
private:
  std::atomic<State> state_{State::Ready};
  std::atomic<uint32_t> pendingStops_{0};
};
