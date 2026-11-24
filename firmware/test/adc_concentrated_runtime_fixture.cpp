#include <cassert>
#include <cstdio>
#include <functional>
#include <vector>
#include <array>
#include <atomic>
#include <thread>
#include <mutex>
#include <condition_variable>
#include "AnalogInputManager.h"
#include "SharedSpiBus.h"
#include "AdcReadyWait.h"
#include "ConfigManager.h"
#include "Rates.h"

constexpr int LOW=0, HIGH=1, INPUT=0, INPUT_PULLUP=2, OUTPUT=3, FALLING=4, RISING=5;
std::atomic<uint32_t> nowUs{100};
bool modelContinuous=true,busHeld=false;
void (*workerFn)(void*)=nullptr;void* workerArg=nullptr;
std::function<void()> waitHook,beforeRead,delayHook;
bool earlyWake=false;
uint32_t micros() { nowUs += 10; return nowUs; }
int64_t esp_timer_get_time() { return micros(); }
void delayMicroseconds(uint32_t us) { nowUs += us; }
void pinMode(uint8_t, int) {}
void digitalWrite(uint8_t, int) {}
int digitalRead(uint8_t);
int analogRead(uint8_t) { return 123; }
uint8_t LoggerConfig::sensorCount() const { return sensorN; }
bool LoggerConfig::getSensorSpec(uint8_t i, SensorSpec& out) const {
  if (i >= sensorN) return false;
  out = sensors[i]; return true;
}

#if ADC_TEST_ASYNC
#define ESP32 1
#define ARDUINO_ISR_ATTR
using BaseType_t=int;
using TickType_t=uint32_t;
using TaskHandle_t=void*;
using portMUX_TYPE=int;
constexpr int portMUX_INITIALIZER_UNLOCKED=0, pdFALSE=0, pdTRUE=1, pdPASS=1;
constexpr uint32_t configTICK_RATE_HZ=1000,portMAX_DELAY=0xffffffff;
constexpr int MALLOC_CAP_INTERNAL=1,MALLOC_CAP_8BIT=2,MALLOC_CAP_DMA=4;
size_t heap_caps_get_free_size(int){return 12000;}
size_t heap_caps_get_largest_free_block(int){return 8192;}
unsigned uxTaskGetStackHighWaterMark(TaskHandle_t){return 1700;}
struct Parked {};
std::atomic<unsigned> notifications{0};
unsigned workerCreations=0;
void xTaskNotifyGive(TaskHandle_t){++notifications;}
constexpr int configMAX_PRIORITIES=25;
#define pdMS_TO_TICKS(ms) (ms)
#define portENTER_CRITICAL(m) ((void)(m))
#define portEXIT_CRITICAL(m) ((void)(m))
#define portENTER_CRITICAL_ISR(m) ((void)(m))
#define portEXIT_CRITICAL_ISR(m) ((void)(m))
#define portYIELD_FROM_ISR() ((void)0)
TaskHandle_t xTaskGetCurrentTaskHandle() { return reinterpret_cast<void*>(1); }
void vTaskNotifyGiveFromISR(TaskHandle_t, BaseType_t*) {++notifications;}
unsigned clears=0;
uint32_t ulTaskNotifyTake(int, TickType_t ticks) {
  if(ticks==portMAX_DELAY){if(!notifications.exchange(0))throw Parked{};return 1;}
  if (!ticks) {++clears;notifications=0;}
  assert(!busHeld);if(ticks && waitHook)waitHook();
  if(ticks && earlyWake){earlyWake=false;return 1;}
  extern uint32_t modelReadyAt();
  if(ticks){uint32_t ready=modelReadyAt();nowUs=ready>nowUs && ready<nowUs+ticks*1000?ready:nowUs+ticks*1000;}return 0;
}
TickType_t xTaskGetTickCount(){return nowUs/1000;}
void vTaskDelay(TickType_t ticks) { assert(!busHeld);nowUs += ticks*1000;if(delayHook)delayHook(); }
void vTaskDelete(TaskHandle_t) {}
void attachInterruptArg(uint8_t, void (*)(void*), void*, int) {}
void detachInterrupt(uint8_t) {}
unsigned failCreateAdc=4;
uint32_t largestInternalBlock=8192;
int xTaskCreatePinnedToCore(void (*fn)(void*), const char*, uint32_t, void* argument, int priority,
                            TaskHandle_t* handle, int core) {
  assert(priority==ADC_TEST_EXPECTED_PRIORITY);
  assert(core==0);
  if(largestInternalBlock<4096 || reinterpret_cast<uintptr_t>(argument)==failCreateAdc) return pdFALSE;
  ++workerCreations;workerFn=fn;workerArg=argument;*handle=xTaskGetCurrentTaskHandle(); return pdPASS;
}
#endif

// PRODUCTION_MANAGER

// Model a task parked in its indefinite notification wait without deleting it.
// Real DRDY-wait/STOP interleavings below still run on a concurrent thread.
void runWorker(){try{workerFn(workerArg);}catch(const Parked&){} }

struct AdcModel {
  std::array<uint8_t,4> regs{};
  unsigned starts=0, reads=0, readyAt=0, generation=0;
  bool active=false;
  bool timeout=false;
};
AdcModel chips[2];
uint32_t modelReadyAt(){return chips[0].timeout?nowUs+100000:chips[0].readyAt;}
struct Transaction { int cs; std::vector<uint8_t> bytes; };
std::vector<Transaction> wire;
int failCommand=-1;
bool completeDuringWrite=false;
unsigned clearCountAtWrite=0;
std::function<void()> afterRead;
namespace SharedSpiBus {
bool begin(const board::SPIProfile&) { return true; }
bool transfer(int8_t cs, const SPISettings& settings, const uint8_t* tx, uint8_t* rx,
              size_t len, uint32_t, uint32_t, uint32_t csSetupUs,SpiTransactionContext* context,SpiTransferTiming* timing) {
  assert(!busHeld);busHeld=true;struct Unlock{~Unlock(){busHeld=false;}} unlock;
  if(context) *context={};
  if(timing) {timing->lockWaitUs=17;timing->prepareUs=11;timing->transferUs=48;timing->finishUs=7;}
  assert(csSetupUs==0); // CAN experiment must not delay the ADC.
  assert(settings.hz==((s_scanSession && cs==10)?BODAQS_ADC_SCAN_SPI_HZ:1000000));
  assert(cs==10 || cs==11);
  auto& chip=chips[cs-10];
  wire.push_back({cs, {tx, tx+len}});
  const uint8_t cmd=tx[0];
  if (failCommand==cmd) {
    failCommand=-1;
    // Model uncertainty: a failed WREG may have changed hardware partially.
    if ((cmd&0xf0)==0x40) chip.regs[0]^=0x30;
    return false;
  }
  if (cmd==0x06) chip=AdcModel{};
  else if ((cmd&0xf0)==0x40) {
#if ADC_TEST_ASYNC
    if (completeDuringWrite) clearCountAtWrite=clears;
#endif
    const unsigned start=(cmd>>2)&3, count=(cmd&3)+1;
    assert((len==count+1 || len==count+2) && start+count<=4);
    for (unsigned i=0;i<count;++i) chip.regs[start+i]=tx[i+1];
    assert((chip.regs[1]&0x04)==(modelContinuous?0x04:0));
    // Do not require WREG alone to wake/start a conversion. Exercise both
    // behaviors; the r1 hardware test failed when explicit START was removed.
    if (ADC_TEST_WREG_STARTS) {
      chip.active=true; ++chip.generation;
      chip.readyAt=nowUs+(completeDuringWrite?0:500);
    }
    if (len==count+2) {
      assert(tx[count+1]==0x08); // decoder resumes after the WREG payload
      ++chip.starts; ++chip.generation; chip.active=true;
      chip.readyAt=nowUs+(completeDuringWrite?0:500);
    }
  } else if(cmd==0x23) {
    assert(len==9 && tx[5]==0x10 && chip.active && !chip.timeout && nowUs>=chip.readyAt);
    if(beforeRead)beforeRead();
    for(unsigned i=0;i<4;++i)rx[i+1]=chip.regs[i];
    // Deliberately identical values across distinct conversions.
    const uint32_t value=(((chip.regs[0]>>4)-8)+1)*100000+chip.generation*1000;
    rx[6]=value>>16;rx[7]=value>>8;rx[8]=value;++chip.reads;
    chip.active=modelContinuous;chip.readyAt=nowUs+1000;
    if(afterRead)afterRead();
  } else if(cmd==0x02) {chip.active=false;
  } else if (cmd==0x10) {
    assert(chip.active && !chip.timeout && nowUs>=chip.readyAt);
    ++chip.reads;
    // Independent channel code and conversion generation identify each result.
    const uint32_t value=(((chip.regs[0]>>4)-8)+1)*100000+chip.generation*1000;
    rx[0]=0; rx[1]=value>>16; rx[2]=value>>8; rx[3]=value;
    chip.active=false;
    if (afterRead) afterRead();
  } else if (cmd==0x08) {
    // The verified baseline sends START as a separate transaction.
    ++chip.starts; ++chip.generation; chip.active=true; chip.readyAt=nowUs+40;
  } else assert(false);
  return true;
}
}
int digitalRead(uint8_t pin) {
  assert(pin==20 || pin==21);
  const auto& c=chips[pin-20];
  return c.active && !c.timeout && nowUs>=c.readyAt ? LOW : HIGH;
}

board::BoardProfile profile() {
  board::BoardProfile p{};
  p.spi.present=true; p.spi.sck=1; p.spi.miso=2; p.spi.mosi=3;
  p.external_adc_count=2; p.analog.count=8;
  for (unsigned a=0;a<2;++a) {
    auto& d=p.external_adcs[a];
    d.present=true; d.type=board::ExternalAdcType::ADS1220;
    d.cs_pin=10+a; d.drdy_pin=20+a; d.channel_count=4; d.max_sps=2000;
    d.reference=board::AdcReferenceType::AnalogSupply;
    for (unsigned ch=0;ch<4;++ch) {
      auto& in=p.analog.inputs[a*4+ch];
      in.source=board::AnalogSourceType::ExternalAdc;
      in.external_adc_index=a; in.external_channel=ch;
    }
  }
  return p;
}
unsigned commands(uint8_t cmd) {
  unsigned n=0; for (const auto& t:wire) if(t.bytes[0]==cmd) ++n; return n;
}
void expect(unsigned index, int cs, std::initializer_list<uint8_t> bytes) {
  assert(index<wire.size());
  if (wire[index].cs!=cs || wire[index].bytes!=std::vector<uint8_t>(bytes)) {
    fprintf(stderr,"transaction %u: cs=%d bytes=",index,wire[index].cs);
    for (auto b:wire[index].bytes) fprintf(stderr,"%02x ",b);
    fprintf(stderr," expected cs=%d bytes=",cs);
    for (auto b:bytes) fprintf(stderr,"%02x ",b);
    fputc('\n',stderr);
  }
  assert(wire[index].cs==cs && wire[index].bytes==std::vector<uint8_t>(bytes));
}
int32_t read(uint8_t ain) {
  int32_t value=-1; assert(AnalogInputManager::readCounts(ain,value)); return value;
}


int main(){
 auto p=profile();AnalogInputManager::begin(p);LoggerConfig cfg;ParamStore params[2];cfg.sensorN=2;
 for(unsigned i=0;i<2;++i){assert(params[i].set("ain",i?"4":"0"));cfg.sensors[i].type=SensorType::AnalogPot;cfg.sensors[i].params.bind(&params[i]);}
 auto start=[&](){chips[0].timeout=chips[1].timeout=false;beforeRead={};afterRead={};waitHook={};failCommand=-1;
  assert(AnalogInputManager::configureFromConfig(cfg,500)==500);wire.clear();
  assert(AnalogInputManager::reserveScanTask()); // Real caller reserves before buffers.
  largestInternalBlock=3572;AnalogInputManager::onLoggingStart();};
 // Same-image split control must keep the original no-worker continuous path.
 start();assert(AnalogInputManager::continuousHealthy() && !s_scanSession && !workerFn);
 assert(chips[0].regs[1]==0xc4 && chips[1].regs[1]==0xc4);
 nowUs+=2000;AnalogInputManager::beginSample();read(0);read(4);AnalogInputManager::endSample();
 AnalogInputManager::onLoggingStop();assert(AnalogInputManager::stoppedTimingStats());
 assert(params[1].set("ain","1"));modelContinuous=false;
 // Reproduce the real allocation boundary: the stack can be reserved early,
 // but a new4096-byte allocation would fail after the recording buffers exist.
 AnalogInputManager::configureFromConfig(cfg,500);wire.clear();failCreateAdc=0;largestInternalBlock=8192;
 assert(!AnalogInputManager::reserveScanTask() && !workerCreations && wire.empty());
 // A direct late start must not create a task or even prime the ADC.
 failCreateAdc=4;largestInternalBlock=3572;AnalogInputManager::onLoggingStart();
 assert(!AnalogInputManager::continuousHealthy() && !workerFn && wire.empty());AnalogInputManager::onLoggingStop();
 largestInternalBlock=8192;wire.clear();assert(AnalogInputManager::reserveScanTask());
 assert(workerCreations==1 && wire.empty() && !s_timingWorkers.load());
 runWorker(); // A storage-start failure/stray wake cannot start conversion.
 assert(wire.empty() && !s_timingWorkers.load());
 largestInternalBlock=3572;
 start();assert(AnalogInputManager::continuousHealthy() && s_scanSession && workerFn);
 assert(commands(0x43)==2 && commands(0x23)==2 && chips[0].regs[1]==0xd0);
 const unsigned primeGeneration=chips[0].generation;
 assert(!AnalogInputManager::stoppedTimingStats());
 for(const auto& t:wire)assert(t.cs==10); // Inactive ADC1 has no session SPI work.
 const unsigned initial=wire.size();AnalogInputManager::beginSample();read(0);read(1);AnalogInputManager::endSample();
 assert(wire.size()==initial); // Row owner only copies the initialized channel caches.
 unsigned completed=0;afterRead=[&](){if(++completed==8)s_scanRun.store(false);};runWorker();afterRead={};
 auto& st=s_timingStats.adc[0];assert(st.scanStarts==10 && st.scanReads==10 && st.channel[0].acquireOk==5 && st.channel[1].acquireOk==5);
 unsigned starts=0;for(const auto& t:wire)if((t.bytes[0]&0xf0)==0x40){
  assert((t.bytes[1]>>4)==8+starts%2);
  const bool shortWrite=BODAQS_ADC_SCAN_MUX_ONLY && starts>=2;
  assert(t.bytes.size()==(shortWrite?3:6) && t.bytes[0]==(shortWrite?0x40:0x43) && t.bytes.back()==0x08);++starts;
 }
 assert(starts==10 && !s_timingWorkers.load() && !s_ads[0].drdyTask);
 assert(st.setupSpi.completed==st.scanStarts && st.readSpi.completed==st.scanReads);
 assert(s_ads[0].cachedCounts[0]==scaleRaw24ToEffectiveBits_(100000+(primeGeneration+7)*1000,s_ads[0].cfg.effective_bits));
 assert(s_ads[0].cachedCounts[1]==scaleRaw24ToEffectiveBits_(200000+(primeGeneration+8)*1000,s_ads[0].cfg.effective_bits));
 AnalogInputManager::onLoggingStop();assert(!chips[0].active && AnalogInputManager::stoppedTimingStats());
 // Absolute deadline bookkeeping, wrap and missing slots: no catch-up loop.
 uint32_t next=100;assert(AdcConcentratedScan::claim(99,next,1).waitTicks==1 && next==100);
 assert(AdcConcentratedScan::claim(100,next,1).missed==0 && next==101);
 assert(AdcConcentratedScan::claim(105,next,1).missed==4 && next==106);
 next=0xfffffffe;assert(AdcConcentratedScan::claim(2,next,1).missed==4 && next==3);
 start();completed=0;afterRead=[&](){++completed;if(completed==2)nowUs+=4500;if(completed==6)s_scanRun.store(false);};
 runWorker();afterRead={};assert(st.scanStarts==8 && st.scanMissedAppointments>=3);
 assert(st.channel[0].acquireOk==4 && st.channel[1].acquireOk==4);AnalogInputManager::onLoggingStop();
 // Actual adapter failures may not publish or relabel the prior channel value.
 for(unsigned reg=0;reg<4;++reg){start();auto seq=s_ads[0].cachedSeq[0];beforeRead=[&](){chips[0].regs[reg]^=1;};
  runWorker();beforeRead={};assert(!AnalogInputManager::continuousHealthy() && st.scanConfigFaults==1 && s_ads[0].cachedSeq[0]==seq);AnalogInputManager::onLoggingStop();}
#if BODAQS_ADC_SCAN_MUX_ONLY
 // Fixed-register corruption before a channel switch is not silently repaired
 // or accepted as a value under the expected image.
 for(unsigned reg=1;reg<4;++reg){start();auto prior=s_ads[0].cachedSeq[0];chips[0].regs[reg]^=1;
  runWorker();assert(!AnalogInputManager::continuousHealthy() && st.scanConfigFaults==1 && s_ads[0].cachedSeq[0]==prior);
  AnalogInputManager::onLoggingStop();}
#endif
 for(int command:{BODAQS_ADC_SCAN_MUX_ONLY?0x40:0x43,0x23}){start();auto seq=s_ads[0].cachedSeq[0];failCommand=command;runWorker();
  assert(!AnalogInputManager::continuousHealthy() && st.scanReadFailures==1 && s_ads[0].cachedSeq[0]==seq);AnalogInputManager::onLoggingStop();}
 start();auto seq=s_ads[0].cachedSeq[0];chips[0].timeout=true;runWorker();
 assert(!AnalogInputManager::continuousHealthy() && st.scanWaitTimeouts==1 && s_ads[0].cachedSeq[0]==seq);AnalogInputManager::onLoggingStop();
 // STOP arriving during the worker wait suppresses data publication and is not a timeout fault.
 start();seq=s_ads[0].cachedSeq[0];waitHook=[&](){s_scanRun.store(false);};runWorker();waitHook={};
 assert(st.scanReads==2 && st.scanWaitTimeouts==0 && s_ads[0].cachedSeq[0]==seq);
 AnalogInputManager::onLoggingStop();assert(!chips[0].active && !s_timingWorkers.load());
 // STOP before the reserved worker has handled its session-start notification
 // must retire that published owner without starting another conversion.
 start();delayHook=[&](){assert(s_timingWorkers.load() && commands(0x02)==0);runWorker();};
 AnalogInputManager::onLoggingStop();delayHook={};
 assert(!s_timingWorkers.load() && !s_scanSession && commands(0x02)==1 && st.scanReads==2 && st.scanStarts==2);
 assert(AnalogInputManager::stoppedTimingStats());
 // Old/spurious notification wakes cannot authorize a GPIO-not-ready read.
 start();unsigned wakes=0;waitHook=[&](){++wakes;};completed=0;earlyWake=true;
 afterRead=[&](){if(++completed==2)s_scanRun.store(false);};runWorker();waitHook={};afterRead={};
 assert(wakes>=3 && st.scanReads==4);AnalogInputManager::onLoggingStop();
 // Run production STOP against a worker actually blocked in DRDY wait. The
 // stop wait yields the worker, which must retire before POWERDOWN/stats.
 start();std::mutex lock;std::condition_variable cv;bool waiting=false,release=false,done=false;
 waitHook=[&](){std::unique_lock<std::mutex> guard(lock);waiting=true;cv.notify_all();cv.wait(guard,[&](){return release;});};
 delayHook=[&](){assert(s_timingWorkers.load() && !AnalogInputManager::stoppedTimingStats());
  assert(commands(0x02)==0);std::unique_lock<std::mutex> guard(lock);release=true;cv.notify_all();cv.wait(guard,[&](){return done;});};
 std::thread running([&](){runWorker();std::lock_guard<std::mutex> guard(lock);done=true;cv.notify_all();});
 {std::unique_lock<std::mutex> guard(lock);cv.wait(guard,[&](){return waiting;});}
 AnalogInputManager::onLoggingStop();running.join();delayHook={};waitHook={};
 assert(done && commands(0x02)==1 && AnalogInputManager::stoppedTimingStats() && st.scanReads==2 && !st.scanWaitTimeouts);
 // A still-owned session rejects reconfigure/start without clearing live cache
 // or counters. This covers a retry after an incomplete retirement.
 start();seq=s_ads[0].cachedSeq[0];const unsigned retainedWire=wire.size();
 AnalogInputManager::configureFromConfig(cfg,200);AnalogInputManager::onLoggingStart();
 assert(!AnalogInputManager::continuousHealthy() && s_ads[0].cachedSeq[0]==seq && st.scanReads==2 && wire.size()==retainedWire);
 runWorker();AnalogInputManager::onLoggingStop();assert(AnalogInputManager::stoppedTimingStats());
 // Task allocation failure, prime failure, exact scope, and restart retirement.
 failCreateAdc=0;start();assert(AnalogInputManager::continuousHealthy() && workerCreations==1);
 completed=0;afterRead=[&](){if(++completed==2)s_scanRun.store(false);};runWorker();afterRead={};
 AnalogInputManager::onLoggingStop();failCreateAdc=4;
 // A stale DRDY notification after STOP is only an idle wake. No old work can
 // touch final counters, caches or hardware; the same worker is reused later.
 auto finalReads=st.scanReads;auto finalWire=wire.size();xTaskNotifyGive(s_scanTask);runWorker();
 assert(st.scanReads==finalReads && wire.size()==finalWire && AnalogInputManager::stoppedTimingStats());
 AnalogInputManager::configureFromConfig(cfg,500);failCommand=0x43;AnalogInputManager::onLoggingStart();
 assert(!AnalogInputManager::continuousHealthy() && !s_timingWorkers.load());AnalogInputManager::onLoggingStop();
 assert(params[0].set("ain","2"));start();assert(!AnalogInputManager::continuousHealthy() && !s_timingWorkers.load());AnalogInputManager::onLoggingStop();
 assert(params[0].set("ain","0"));start();completed=0;afterRead=[&](){if(++completed==2)s_scanRun.store(false);};runWorker();afterRead={};
 assert(st.scanReads==4 && st.scanStarts==4 && st.scanReadFailures==0 && st.scanConfigFaults==0 && st.scanWaitTimeouts==0);AnalogInputManager::onLoggingStop();
 // Startup refreshes both immutable images; no cached register template from a
 // prior stopped session may be used after effective device settings change.
 s_ads[0].cfg.gain=2;start();assert((chips[0].regs[0]&0x0e)==2);
 completed=0;afterRead=[&](){if(++completed==2)s_scanRun.store(false);};runWorker();afterRead={};
 assert(st.scanReads==4 && !st.scanConfigFaults);AnalogInputManager::onLoggingStop();s_ads[0].cfg.gain=1;
 assert(workerCreations==1);
 puts("PASS early reservation under real late-block limit, persistent idle/restart worker, actual concentrated worker: distinct channel attribution, verified single-shot results, notification wait with bus released, bounded appointments/skip/wrap, faults, STOP-in-wait, inactive ADC, allocation/start/restart and unchanged split control");
}
