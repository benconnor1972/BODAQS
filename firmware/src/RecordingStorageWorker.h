#pragma once
#include <atomic>
#include <cstdint>

// The sink is called only by the persistent storage task. Control never waits
// for the sink and never closes a handle owned by an outstanding operation.
struct RecordingStorageSink {
  virtual ~RecordingStorageSink() = default;
  virtual bool healthCheck() = 0;
  virtual bool start() = 0;
  virtual bool service() = 0;
  virtual bool stop(bool clean) = 0;
};

class RecordingStorageWorker {
 public:
  enum class Fault : uint8_t { None, Failure, Unresponsive };
  explicit RecordingStorageWorker(RecordingStorageSink& sink) : sink_(sink) {}
  bool requestStart() {
    if (busy_.load()) return false;
    State expected = State::Idle;
    if (!state_.compare_exchange_strong(expected, State::Reserved)) return false;
    fault_.store(Fault::None);
    stop_.store(false);
    state_.store(State::Starting);
    return true;
  }
  void requestStop() { stop_.store(true); }
  bool pending() const { return state_.load() != State::Idle || busy_.load(); }
  bool recording() const { return state_.load() == State::Recording; }
  Fault fault() const { return fault_.load(); }
  void poll(uint32_t nowMs) {
    if (busy_.load() && int32_t(nowMs - beganMs_.load()) >= 5000) {
      fault_.store(Fault::Unresponsive);
    }
  }
  // Exactly one owner calls step; time is supplied before entering I/O.
  void step(uint32_t nowMs) {
    const auto state = state_.load();
    if (state == State::Idle || state == State::Reserved) return;
    beganMs_.store(nowMs);
    busy_.store(true);
    if (state == State::Starting) {
      // Every explicit start probes storage, including recovery after a fault.
      const bool healthy = sink_.healthCheck();
      const bool opened = healthy && !stop_.load() && sink_.start();
      if (!healthy || (!opened && !stop_.load())) fail_();
      if (opened) state_.store(State::Recording);
      else state_.store(State::Idle);
    } else if (stop_.load()) {
      const bool clean = fault_.load() == Fault::None;
      if (!sink_.stop(clean)) fail_();
      state_.store(State::Idle);
    } else if (fault_.load() == Fault::None && !sink_.service()) {
      fail_();
    }
    busy_.store(false);
  }
 private:
  enum class State : uint8_t { Idle, Reserved, Starting, Recording };
  void fail_() {
    Fault expected = Fault::None;
    fault_.compare_exchange_strong(expected, Fault::Failure);
  }
  RecordingStorageSink& sink_;
  std::atomic<State> state_{State::Idle};
  std::atomic<Fault> fault_{Fault::None};
  std::atomic<bool> stop_{false}, busy_{false};
  std::atomic<uint32_t> beganMs_{0};
};
