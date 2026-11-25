#include <cassert>
#include <cmath>
#include <cstring>
#include <deque>
#include <thread>
#include "BMI270SparseRow.h"
#include "BMI270PublishedSnapshot.h"
#include "BMI270BdqV2.h"
static uint64_t nowUs = 100000;
static uint64_t esp_timer_get_time() { return nowUs; }
struct BMI270IocOffsetSnapshot { int16_t x=0,y=0,z=0; uint32_t nativeSequence=0; };
struct Acquisition {
  std::deque<BMI270ImuSample> recording;
  BMI270PublishedSnapshot<BMI270ImuSample> published;
  bool latestSample(BMI270ImuSample& value) const { return published.read(value); }
  BMI270PublishedSnapshot<BMI270IocOffsetSnapshot> publishedIoc;
  std::deque<BMI270IocOffsetSnapshot> offsets;
  bool latestIocOffsetSnapshot(BMI270IocOffsetSnapshot& value) const { return publishedIoc.read(value); }
  bool pop(BMI270ImuSample& value) { if(recording.empty()) return false; value=recording.front(); recording.pop_front(); return true; }
  bool popIocOffsetSnapshot(BMI270IocOffsetSnapshot& value) {
    if(offsets.empty()) return false;
    value=offsets.front();
    offsets.pop_front();
    return true;
  }
  unsigned rowEmissions=0;
  void recordRowEmission(uint32_t,bool) {
#if BODAQS_PRODUCTION_RECORDING
    assert(false && "preview changes recording diagnostics");
#else
    ++rowEmissions;
#endif
  }
};
struct I2CBusScheduler { static void recordRowUse(Acquisition*,uint32_t,bool,bool) {} };
class BMI270ImuSensor {
public:
  static constexpr uint8_t kMaximumColumnCount=16;
  struct { bool iocDiagnostics=false; } params_;
  Acquisition acquisition_;
  uint8_t columnCount() const { return params_.iocDiagnostics ? 16 : 12; }
  void sampleValues(float*,uint8_t);
};
// PRODUCTION_PREVIEW
static constexpr uint8_t kFinalDrainPasses=4;
class BMI270FifoAcquisition {
public:
  std::atomic<bool> sessionActive_{true};
  struct { bool sessionActive=true; uint64_t stopDrainAttempts=0,stopDrainFailures=0; } diagnostics_;
  struct Watchdog { void disarm() {} } progressWatchdog_;
  struct Device { bool suspendOk=true; bool suspended=false; bool suspend() { suspended=true; return suspendOk; } } device_;
  struct Observer { void finish() {} } startupObservation_;
  std::deque<int> recorded;
  bool drainOk=true;
  bool sessionActive() const { return sessionActive_.load(); }
  void addCounter_(uint64_t& count) { ++count; }
  bool drainAllAvailable_(uint8_t passes,bool temperature,bool requireEmpty) {
    assert(!sessionActive() && device_.suspended && passes==4 && !temperature && requireEmpty);
    recorded.push_back(-700); return drainOk;
  }
  bool stopSession();
};
// PRODUCTION_RETIREMENT
int main() {
  BMI270PublishedSnapshot<BMI270ImuSample> concurrent;
  std::thread writer([&]() {
    for (uint32_t sequence=1; sequence<=50000; ++sequence) {
      BMI270ImuSample value;
      value.sequence=sequence;
      value.accelX=static_cast<int16_t>(sequence % 10000);
      value.acquisitionAnchorUs=(uint64_t{sequence} << 32) | sequence;
      concurrent.publish(value);
    }
  });
  for (unsigned attempt=0; attempt<50000; ++attempt) {
    BMI270ImuSample value;
    if (concurrent.read(value)) {
      assert(value.accelX==static_cast<int16_t>(value.sequence % 10000));
      assert(uint32_t(value.acquisitionAnchorUs)==value.sequence);
      assert(uint32_t(value.acquisitionAnchorUs >> 32)==value.sequence);
    }
  }
  writer.join();
  BMI270ImuSample last;
  assert(concurrent.read(last) && last.sequence==50000);
  concurrent.invalidate();
  assert(!concurrent.read(last));

  BMI270FifoAcquisition stopping;
  assert(stopping.stopSession());
  assert(!stopping.sessionActive() && stopping.recorded.front()==-700);
  assert(stopping.stopSession() && stopping.recorded.size()==1);
  BMI270FifoAcquisition failed;
  failed.drainOk=false;
  assert(!failed.stopSession() && failed.diagnostics_.stopDrainFailures==1);
  assert(!failed.sessionActive());
  BMI270ImuSensor sensor;
  float out[16]{};
  sensor.sampleValues(out,16);
  assert(out[11]==0 && std::isnan(out[9]));
  BMI270ImuSample evidence;
  evidence.accelX=-32768; evidence.gyroZ=-1024; evidence.temperatureRaw=-512;
  evidence.sequence=19; evidence.sensorTime=256; evidence.acquisitionAnchorUs=99000;
  evidence.statusFlags=BMI270ImuStatus::kFifoDiscontinuityBefore;
  sensor.acquisition_.recording.push_back(evidence);
  sensor.acquisition_.published.publish(evidence);
  sensor.params_.iocDiagnostics=true;
  BMI270IocOffsetSnapshot ioc; ioc.x=-17; ioc.y=25; ioc.z=-31;
  sensor.acquisition_.publishedIoc.publish(ioc);
  sensor.acquisition_.offsets.push_back(ioc);
#if BODAQS_PRODUCTION_RECORDING
  for(int i=0;i<3;++i) {
    sensor.sampleValues(out,16);
    assert(out[0]==-32768 && out[5]==-1024 && out[8]==-512);
    assert(out[7]==19 && out[9]==1000 && out[11]==1);
    assert(out[12]==-17 && out[13]==25 && out[14]==-31 && out[15]==1);
  }
  assert(sensor.acquisition_.recording.size()==1);
  assert(sensor.acquisition_.offsets.size()==1);
  BMI270ImuSample recorded;
  assert(sensor.acquisition_.pop(recorded));
#else
  sensor.sampleValues(out,16);
  assert(out[7]==19 && out[11]==1 && out[12]==-17 && out[15]==1);
  assert(sensor.acquisition_.recording.empty() && sensor.acquisition_.offsets.empty());
  sensor.sampleValues(out,16);assert(out[11]==0 && out[15]==0);
  assert(sensor.acquisition_.rowEmissions==1);
  BMI270ImuSample recorded=evidence;
#endif
  uint8_t bytes[28]; assert(BMI270BdqV2::encodeRecord(recorded,bytes,sizeof(bytes)));
  assert(BdqV2Format::getU16(bytes+12)==0x8000 && BdqV2Format::getU16(bytes+24)==0xfe00);
  sensor.acquisition_.published.invalidate(); // restart invalidates the published epoch
  sensor.sampleValues(out,16);
  assert(out[11]==0 && std::isnan(out[9]));
}
