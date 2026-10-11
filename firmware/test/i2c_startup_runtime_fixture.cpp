#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstring>
#define ESP32 1
#define LOGI_TAG(...) ((void)0)
#define LOGW_TAG(...) ((void)0)
namespace StartupLog { template <typename... Args> void recordf(const char*, Args...) {} }
#define I2C_BUFFER_LENGTH 128
constexpr int ESP_OK = 0, ESP_FAIL = -1, ESP_ERR_INVALID_ARG = 258;
constexpr int ESP_ERR_INVALID_STATE = 259, ESP_ERR_TIMEOUT = 263;
constexpr int LOW = 0, HIGH = 1, INPUT_PULLUP = 1, OUTPUT_OPEN_DRAIN = 2;
struct TwoWire {
  unsigned number, hz = 0, starts = 0, ends = 0;
  bool beginOk = true, clockOk = true, restoreOk = true, bufferOk = true;
  uint16_t timeout = 50;
  explicit TwoWire(unsigned n) : number(n) {}
  bool begin(int, int, unsigned rate) { ++starts; hz = rate; return beginOk; }
  bool end() { ++ends; return true; }
  bool setClock(unsigned rate) {
    if (!clockOk || (!restoreOk && rate == 400000)) return false;
    hz = rate; return true;
  }
  unsigned getClock() { return hz; }
  void setTimeOut(uint16_t ms) { timeout = ms; }
  uint16_t getTimeOut() { return timeout; }
  unsigned setBufferSize(unsigned size) { return bufferOk ? size : 0; }
};
TwoWire Wire(0);
#include "I2CManager.h"
struct Mutex { bool held = false; };
using SemaphoreHandle_t = Mutex*;
using TickType_t = unsigned;
constexpr int pdTRUE = 1;
#define pdMS_TO_TICKS(v) (v)
bool mutexAllocationOk = true, mutexTakeOk = true;
Mutex mutexPool[2];
unsigned nextMutex = 0;
SemaphoreHandle_t xSemaphoreCreateMutex() {
  return mutexAllocationOk ? &mutexPool[nextMutex++ % 2] : nullptr;
}
int xSemaphoreTake(Mutex* m, TickType_t) {
  if (!mutexTakeOk || m->held) return 0;
  m->held = true; return pdTRUE;
}
void xSemaphoreGive(Mutex* m) { m->held = false; }
unsigned nowMs = 100, pinLevels[64], pulses = 0;
unsigned millis() { return nowMs; }
void delayMicroseconds(unsigned) {}
void pinMode(unsigned, int) {}
int digitalRead(unsigned pin) { return pinLevels[pin]; }
void digitalWrite(unsigned pin, int value) {
  pinLevels[pin] = value;
  if (value == HIGH) ++pulses;
}
namespace I2CBusScheduler {
bool running = false, registrationOk = true;
bool isRunning() { return running; }
template <class T> bool registerClient(T*) { return registrationOk; }
}
int halError = ESP_OK;
size_t halReceived = 1;
uint8_t halByte = 0x24;
unsigned halCalls = 0, halHz = 0;
int i2cWriteReadNonStop(unsigned bus, uint16_t, const uint8_t*, size_t,
                        uint8_t* out, size_t, unsigned, size_t* received);
// PRODUCTION_MANAGER
int i2cWriteReadNonStop(unsigned bus, uint16_t, const uint8_t*, size_t,
                        uint8_t* out, size_t, unsigned, size_t* received) {
  ++halCalls; halHz = s_buses[bus]->hz; *received = halReceived;
  out[0] = halByte; return halError;
}

enum class BMI270DeviceStep { None, ProbeChipId };
enum class BMI270I2CFailureStage { None, RequestBytes };
struct DeviceDiagnostics {
  BMI270DeviceStep failureStep = BMI270DeviceStep::None;
  bool chipIdRead = false, chipIdMatched = false;
};
struct TransportDiagnostics {
  unsigned failures = 0;
  struct { BMI270I2CFailureStage stage = BMI270I2CFailureStage::None; } lastFailure;
};
struct FakeDevice {
  enum Failure { None, WrongId, Transport, Other } mode = None;
  unsigned beginCalls = 0, shutdowns = 0;
  bool secondBeginOk = true, suspended = true;
  DeviceDiagnostics diag;
  TransportDiagnostics transport;
  unsigned busIndex() const { return 1; }
  bool begin() {
    ++beginCalls;
    if (mode == None || (beginCalls > 1 && secondBeginOk)) return true;
    diag.failureStep = mode == Other ? BMI270DeviceStep::None : BMI270DeviceStep::ProbeChipId;
    diag.chipIdRead = mode == WrongId;
    if (mode == Transport) {
      ++transport.failures; transport.lastFailure.stage = BMI270I2CFailureStage::RequestBytes;
    }
    return false;
  }
  bool suspend() { return suspended; }
  void shutdown() { ++shutdowns; }
  const DeviceDiagnostics& diagnostics() const { return diag; }
  const TransportDiagnostics& transportDiagnostics() const { return transport; }
};
struct ScopedOledTransferDeferral { explicit ScopedOledTransferDeferral(unsigned) {} };
#define BMI270_FIFO_LOGW(...) ((void)0)
#define BMI270_FIFO_LOGI(...) ((void)0)
class BMI270FifoAcquisition {
public:
  bool begin(bool allowBusRecovery = true);
  bool initialized_ = false, registered_ = false, fifoOk = true;
  std::atomic<bool> sessionActive_ {false};
  struct { unsigned bytes = 64; unsigned capacity() { return bytes; } } queue_;
  FakeDevice device_;
  static constexpr unsigned kRawBufferBytes = 2304;
  bool configureFifo_() { return fifoOk; }
  bool busCommunicationFailure_(BMI270I2CFailureStage s) { return s == BMI270I2CFailureStage::RequestBytes; }
};
// PRODUCTION_FIFO_BEGIN

board::BoardProfile profile;
void reset() {
  profile = board::BoardProfile{};
  profile.i2c_count = 2;
  profile.i2c[0] = {true, 1, 2, 400000};
  profile.i2c[1] = {true, 4, 5, 400000};
  Wire = TwoWire(0); s_wire1 = TwoWire(1);
  std::memset(pinLevels, 1, sizeof(pinLevels));
  for (auto& value : pinLevels) value = HIGH;
  for (auto& m : mutexPool) m.held = false;
  for (auto& m : s_mutexes) m = nullptr;
  mutexAllocationOk = mutexTakeOk = true;
  nextMutex = pulses = halCalls = 0;
  nowMs = 100; halError = ESP_OK; halReceived = 1; halByte = 0x24;
  I2CBusScheduler::running = false; I2CBusScheduler::registrationOk = true;
  I2CManager::resetRecoveryStats();
  I2CManager::begin(profile);
}

int main() {
  unsigned passed = 0, failed = 0;
#define CHECK(c) do { if (c) ++passed; else { ++failed; std::printf("FAIL startup runtime line %d: %s\n", __LINE__, #c); } } while (0)
  reset();
  CHECK(I2CManager::available(0) && I2CManager::available(1));
  CHECK(Wire.hz == 400000 && s_wire1.hz == 400000);
  Wire.beginOk = false; I2CManager::begin(profile);
  CHECK(!I2CManager::available(0) && I2CManager::available(1));
  Wire.beginOk = true;
  CHECK(I2CManager::recoverBus(0, true) && I2CManager::available(0));
  Wire.clockOk = false; I2CManager::begin(profile);
  CHECK(!I2CManager::available(0));
  reset(); s_mutexes[0] = nullptr;
  CHECK(!I2CManager::lock(&Wire));
  reset(); s_mutexes[0] = nullptr; mutexAllocationOk = false;
  I2CManager::begin(profile);
  CHECK(!I2CManager::available(0));

  reset();
  CHECK(I2CManager::setStartupClockOverride(1, 100000));
  CHECK(I2CManager::clockHz(1) == 100000 && s_wire1.hz == 100000);
  auto probe = I2CManager::probeRegister(1, 0x68, 0x00, 1);
  CHECK(probe.ok && probe.bytes[0] == 0x24 && probe.received == 1 && halHz == 100000);
  halError = ESP_FAIL; halReceived = 0;
  probe = I2CManager::probeRegister(1, 0x68, 0x00, 1);
  CHECK(!probe.ok && probe.error == ESP_FAIL && probe.received == 0);
  halError = ESP_OK; halReceived = 0;
  CHECK(!I2CManager::probeRegister(1, 0x68, 0x00, 1).ok);
  halReceived = 1; halByte = 0x20;
  probe = I2CManager::probeRegister(1, 0x68, 0x00, 1);
  CHECK(probe.ok && probe.bytes[0] == 0x20); // never conceal a wrong byte
  CHECK(!mutexPool[1].held);
  CHECK(I2CManager::probeRegister(1, 0x68, 0x00, 3).error == ESP_ERR_INVALID_ARG);
  CHECK(I2CManager::probeRegister(2, 0x68, 0x00, 1).error == ESP_ERR_INVALID_STATE);
  CHECK(I2CManager::setStartupClockOverride(1, 0) && s_wire1.hz == 400000);
  I2CBusScheduler::running = true;
  CHECK(!I2CManager::setStartupClockOverride(1, 100000));
  CHECK(!I2CManager::recoverBus(1, true));
  reset(); I2CManager::setStartupClockOverride(1, 100000); s_wire1.restoreOk = false;
  CHECK(!I2CManager::setStartupClockOverride(1, 0));
  CHECK(!I2CManager::available(1) && I2CManager::clockHz(1) == 400000);
  reset(); I2CManager::setStartupClockOverride(1, 100000); mutexTakeOk = false;
  CHECK(!I2CManager::setStartupClockOverride(1, 0));
  CHECK(!I2CManager::available(1) && I2CManager::clockHz(1) == 400000);

  reset(); CHECK(I2CManager::recoverBus(1));
  CHECK(pulses == 0 && !I2CManager::recoveryStatus(1).sdaLowBefore);
  const unsigned starts = s_wire1.starts;
  CHECK(I2CManager::recoverBus(1) && s_wire1.starts == starts);
  CHECK(I2CManager::recoverBus(1, true) && s_wire1.starts == starts + 1);
  reset(); pinLevels[4] = LOW;
  CHECK(I2CManager::recoverBus(1, true));
  CHECK(I2CManager::recoveryStatus(1).sdaLowBefore && I2CManager::recoveryStatus(1).clockPulses == 9);
  reset(); pinLevels[5] = LOW;
  CHECK(!I2CManager::recoverBus(1, true) && !I2CManager::available(1));
  reset(); s_wire1.bufferOk = false;
  CHECK(!I2CManager::recoverBus(1, true));
  reset(); s_wire1.clockOk = false;
  CHECK(!I2CManager::recoverBus(1, true));
  reset(); mutexTakeOk = false;
  CHECK(!I2CManager::recoverBus(1, true));

  reset(); BMI270FifoAcquisition fifo; fifo.device_.mode = FakeDevice::WrongId;
  CHECK(fifo.begin() && fifo.device_.beginCalls == 2);
  CHECK(I2CManager::recoveryStatus(1).attempts == 1);
  reset(); BMI270FifoAcquisition blocked; blocked.device_.mode = FakeDevice::WrongId;
  CHECK(!blocked.begin(false) && blocked.device_.beginCalls == 1);
  CHECK(I2CManager::recoveryStatus(1).attempts == 0);
  reset(); BMI270FifoAcquisition persistent; persistent.device_.mode = FakeDevice::WrongId;
  persistent.device_.secondBeginOk = false;
  CHECK(!persistent.begin() && persistent.device_.beginCalls == 2);
  CHECK(I2CManager::recoveryStatus(1).attempts == 1);
  reset(); BMI270FifoAcquisition transport; transport.device_.mode = FakeDevice::Transport;
  CHECK(transport.begin() && transport.device_.beginCalls == 2);
  CHECK(I2CManager::recoveryStatus(1).attempts == 1);
  reset(); BMI270FifoAcquisition other; other.device_.mode = FakeDevice::Other;
  CHECK(!other.begin() && other.device_.beginCalls == 1);
  CHECK(I2CManager::recoveryStatus(1).attempts == 0);
  reset(); BMI270FifoAcquisition queue; queue.queue_.bytes = 0;
  CHECK(!queue.begin() && queue.device_.beginCalls == 0);
  reset(); BMI270FifoAcquisition config; config.fifoOk = false;
  CHECK(!config.begin() && config.device_.shutdowns == 1);
  reset(); BMI270FifoAcquisition registration; I2CBusScheduler::registrationOk = false;
  CHECK(!registration.begin() && registration.device_.shutdowns == 1);
  std::printf("Startup production runtime: %u passed, %u failed\n", passed, failed);
  return failed ? 1 : 0;
}
