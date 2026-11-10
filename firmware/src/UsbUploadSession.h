#pragma once
#include <cstdint>

// Upload/storage coordination boundary. USB and SD drivers supply observations;
// only the main loop performs handoff/reclaim, never a USB callback.
class UsbUploadSession {
public:
  enum class State : uint8_t { Normal, Upload, Waiting, Shared, Disconnecting, Reclaiming, Ejected, Error };
  struct Inputs {
    bool connected = false;
    bool present = false;
    bool busy = false;
    bool ejected = false;
    bool ioFailed = false;
    uint32_t lastIoMs = 0;
  };
  struct Backend {
    virtual ~Backend() = default;
    virtual bool localReady() const = 0;
    virtual bool requestStorage() = 0;
    virtual bool storageGranted() const = 0;
    virtual void cancelStorage() = 0;
    virtual bool expose() = 0;
    // Atomically stop admission and finish in-flight raw I/O. For normal exit,
    // recheck the quiet interval under the transport lock; false means retry.
    virtual bool withdraw(bool requireQuiet) = 0;
    virtual bool reclaim() = 0;
  };
  explicit UsbUploadSession(Backend& backend) : backend_(backend) {}
  bool enter(bool logging);
  void requestExit(uint32_t now);
  bool cancelExit();
  void retry() { retry_ = true; }
  void poll(const Inputs& input, uint32_t now);
  bool active() const { return active_; }
  bool exitPending() const { return exit_; }
  State state() const { return state_; }
  const char* label() const;
  const char* stateKey() const;
  const char* shortLabel() const;
private:
  Backend& backend_;
  State state_ = State::Normal;
  bool active_ = false, exit_ = false, suppressed_ = false, retry_ = false;
  bool wasConnected_ = false;
  uint32_t exitRequestedMs_ = 0;
  const char* error_ = nullptr;
};
