#include "AnalogInputManager.h"
#include "SharedSpiBus.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include <atomic>
#include <cassert>
#include <chrono>
#include <condition_variable>
#include <thread>
#include <vector>
#include <algorithm>
#include <cstdarg>
#if TEST_CASE_RUNNER
#include "SpiMeasurementProbe.h"
#include "SpiProbeTransport.h"
#include "../can-fd/common/protocol/bodaqs_spi_probe.h"
#include <array>
#include <deque>
static BodaqsSpiProbeEngine master;
static bool masterEnabled=false,masterSilent=false,corruptPayload=false;
static unsigned rawFault=0,rawFaultsLeft=0;
static std::vector<std::array<uint8_t,256>> injectedRx;
static bool stats2Unsupported=false;
static unsigned syntheticSwitchCount=0;
static std::deque<std::array<uint8_t,256>> replies(2);
static uint64_t bulkLastHigh=0;
// Rail fault signal boundary only; target build retains real PowerManager.
static bool railFault=false;
namespace PowerManager {
bool analogRailFaultActive() {return railFault;}
bool analogRailFaultLatched() {return railFault;}
bool analogRailEnabled() {return true;}
}
#endif
// CONFIG_SUPPORT

static const auto epoch = std::chrono::steady_clock::now();
static std::atomic<int64_t> frozenUs{-1};
unsigned long micros() { if(frozenUs>=0)return (unsigned long)frozenUs.load();return (unsigned long)std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now()-epoch).count(); }
unsigned long millis() { return micros()/1000; }
int64_t esp_timer_get_time() { return micros(); }
void delay(unsigned long ms) { std::this_thread::sleep_for(std::chrono::milliseconds(ms)); }
void delayMicroseconds(unsigned int us) { std::this_thread::sleep_for(std::chrono::microseconds(us)); }
void pinMode(uint8_t, uint8_t) {}
int analogRead(uint8_t) { return 0; }
static std::atomic<int> selected{-1};
static std::atomic<uint8_t> pinLevel[64];
static std::atomic<bool> forceReadyPin=false;
static std::mutex gpioMutex;
struct Gpio { int level=LOW; void (*isr)(void*)=nullptr; void* arg=nullptr; } gpio[64];
static std::atomic<unsigned> starts[2], reads[2];
static std::atomic<bool> failRead[2], timeoutReady[2];
static thread_local int workerAdc=-1;
static thread_local unsigned workerLockCalls=0;
static thread_local bool workerStartTransfer=false;
static std::atomic<bool> injectBeforeStart[2];
static std::atomic<bool> delayReadLock[2],failReadLock[2];
static std::atomic<unsigned long> readCsUs[2],edgeUs[2];
static void complete(int adc,int count=1);
static std::atomic<bool> holdStartTransfer=false,startTransferReached=false,holdTieIsr=false,tieIsrReached=false;
static std::mutex tieMutex;
static std::condition_variable tieCv;
static thread_local bool injectedTieIsr=false;
void probeEnterCriticalIsr(portMUX_TYPE* mux) {
  if(injectedTieIsr && holdTieIsr) {
    std::unique_lock<std::mutex> lock(tieMutex);
    tieIsrReached=true;tieCv.notify_all();tieCv.wait(lock,[]{return !holdTieIsr;});
  }
  mux->lock();
}
void digitalWrite(uint8_t pin,uint8_t level) { pinLevel[pin]=level; if (level==LOW) { assert(selected.exchange(pin)==-1); if(workerAdc>=0 && workerLockCalls==3)readCsUs[workerAdc]=micros();
#if TEST_CASE_RUNNER
  if(pin==40 && masterEnabled && bulkLastHigh)assert(esp_timer_get_time()-bulkLastHigh>=25);
#endif
  } else if(selected==pin) {
#if TEST_CASE_RUNNER
    if(pin==40 && masterEnabled)bulkLastHigh=esp_timer_get_time();
#endif
    selected=-1;
  } }
int digitalRead(uint8_t pin) { std::lock_guard<std::mutex> lock(gpioMutex); return forceReadyPin && (pin==18 || pin==36)?LOW:gpio[pin].level; }
void attachInterruptArg(uint8_t pin,void (*fn)(void*),void* arg,int) { std::lock_guard<std::mutex> lock(gpioMutex); gpio[pin].isr=fn; gpio[pin].arg=arg; }
void detachInterrupt(uint8_t pin) { std::lock_guard<std::mutex> lock(gpioMutex); gpio[pin].isr=nullptr; }
SPIClass SPI;
ProbeSerial Serial;
void ProbeSerial::printf(const char* format,...) {char out[1024];va_list args;va_start(args,format);int n=vsnprintf(out,sizeof(out),format,args);va_end(args);assert(n>=0 && n<(int)sizeof(out));output+=out;}
void SPIClass::begin(int8_t,int8_t,int8_t) {}
static SPISettings settings;
void SPIClass::beginTransaction(const SPISettings& requested) { settings=requested; }
void SPIClass::endTransaction() {}
void SPIClass::transferBytes(const uint8_t* tx,uint8_t* rx,size_t length) {
  if(selected<0) {
    assert(settings.hz==1000000 && settings.mode==SPI_MODE1 && length==4);
    const auto& bus=board::GetBoardProfile(board::BoardID::BODAQS_A8).spi;
    for(uint8_t i=0;i<bus.cs_count && i<8;++i)if(bus.cs_pins[i]>=0)assert(pinLevel[bus.cs_pins[i]]==HIGH);
#if TEST_CASE_RUNNER
    ++syntheticSwitchCount;
#endif
    return;
  }
  delayMicroseconds(10); if(rx) memset(rx,0,length);
  const int adc=selected==47?0:selected==21?1:-1;
  if(adc>=0)assert(settings.hz==1000000 && settings.mode==SPI_MODE1);
  if(selected==40)assert((settings.hz==16000000 || settings.hz==8000000) && settings.mode==SPI_MODE0);
#if TEST_CASE_RUNNER
  if(selected==40 && masterEnabled) {
    if(rx)memcpy(rx,replies.front().data(),length);replies.pop_front();
    if(rx && rawFaultsLeft) {
      // Inject independent raw hardware replies, after the real master encoder.
      --rawFaultsLeft;
      if(rawFault==3)rx[0]=0;
      if(rawFault==4)rx[2]=2;
      if(rawFault==5)rx[15]=255;
      if(rawFault==6)rx[14]=255;
      if(rawFault==7)rx[length-1]^=0x80;
      if(rawFault==8) {
        rx[14]=0;rx[20]=1;
        // IEEE CRC32 independently written at the hardware boundary, so only
        // padding fails; do not ask the codec under test to construct the fault.
        uint32_t crc=0xffffffffU;
        for(size_t i=0;i<length-4;++i){crc^=rx[i];for(unsigned b=0;b<8;++b)crc=(crc&1)?(crc>>1)^0xedb88320U:crc>>1;}
        crc^=0xffffffffU;for(unsigned b=0;b<4;++b)rx[length-4+b]=crc>>(8*b);
      }
      std::array<uint8_t,256> observed{};memcpy(observed.data(),rx,length);injectedRx.push_back(observed);
    }
    std::array<uint8_t,256> prepared{};
    if(!masterSilent)bodaqs_spi_probe_process(&master,tx,length,prepared.data(),prepared.size());
    BodaqsSpiProbeFrame response;
    if(stats2Unsupported && bodaqs_spi_probe_decode(prepared.data(),length,&response) && response.opcode==(BODAQS_PROBE_STATS|BODAQS_PROBE_RESPONSE) && response.fragment==2) {
      response.opcode=BODAQS_PROBE_ERROR|BODAQS_PROBE_RESPONSE;response.payload_length=1;response.payload[0]=BODAQS_PROBE_ARGUMENT;
      assert(bodaqs_spi_probe_encode(&response,prepared.data(),length));
    }
    if(corruptPayload && bodaqs_spi_probe_decode(prepared.data(),length,&response) && response.opcode==(BODAQS_PROBE_POLL|BODAQS_PROBE_RESPONSE) && response.fragment==2) {
      response.payload[0]^=1;assert(bodaqs_spi_probe_encode(&response,prepared.data(),length));corruptPayload=false;
    }
    replies.push_back(prepared);return;
  }
#endif
  if(adc>=0 && tx && tx[0]==8) {
    if(workerAdc==0 && holdStartTransfer) {
      std::unique_lock<std::mutex> lock(tieMutex);
      startTransferReached=true;tieCv.notify_all();tieCv.wait(lock,[]{return !holdStartTransfer;});
    }
    { std::lock_guard<std::mutex> lock(gpioMutex); gpio[adc?18:36].level=workerAdc>=0?HIGH:LOW; }
    if(workerAdc>=0)workerStartTransfer=true;
  }
  if(adc>=0 && tx && tx[0]==16) ++reads[adc];
}
static SemaphoreHandle_t sharedSpiLock=nullptr;
static thread_local bool holdContextAcquisition=false;
static std::atomic<bool> contextAcquisitionReached=false,releaseContextAcquisition=false;
SemaphoreHandle_t xSemaphoreCreateMutex() {
  auto* mutex=new std::timed_mutex;
  if(!sharedSpiLock)sharedSpiLock=mutex;
  return mutex;
}
static std::atomic<bool> failLock=false,failWarmup=false,failInterruptRegistration=false;
BaseType_t xSemaphoreTake(SemaphoreHandle_t m,TickType_t timeout) {
  if(m==sharedSpiLock && holdContextAcquisition) {
    contextAcquisitionReached=true;
    while(!releaseContextAcquisition)std::this_thread::yield();
  }
  // Faults and lock-call ordinals below describe SPI contention, not the
  // independent ADC interrupt-registration mutex.
  if(m!=sharedSpiLock)return !failInterruptRegistration && m->try_lock_for(std::chrono::milliseconds(timeout));
  if(workerAdc>=0 && ++workerLockCalls==2 && injectBeforeStart[workerAdc].exchange(false)) {
    // An older conversion's ISR dispatch while START waits behind another CS.
    std::lock_guard<std::timed_mutex> owner(*m); complete(workerAdc);delay(2);
  }
  if(workerAdc>=0 && workerLockCalls==3) {
    if(delayReadLock[workerAdc].exchange(false)) {std::lock_guard<std::timed_mutex> owner(*m);delay(5);}
    if(failReadLock[workerAdc].exchange(false)) return pdFALSE;
  }
  return !failLock && !(workerAdc<0 && failWarmup) && !(workerAdc>=0 && failRead[workerAdc]) && m->try_lock_for(std::chrono::milliseconds(timeout));
}
void xSemaphoreGive(SemaphoreHandle_t m) { m->unlock();if(workerStartTransfer) {workerStartTransfer=false;++starts[workerAdc];} }
struct FakeTask { std::thread thread; std::mutex mutex; std::condition_variable cv; unsigned notifications=0;std::atomic<bool> exited=false; };
static thread_local FakeTask* current=nullptr;
static std::vector<FakeTask*> tasks;
static int failTask=-1;
static std::atomic<bool> holdWorkers=false;
static std::atomic<bool> releaseWaiters=false;
static std::atomic<bool> holdTaskEntry=false;
static std::mutex entryMutex;
static std::condition_variable entryCv;
static std::mutex exitMutex;
static std::condition_variable exitCv;
BaseType_t xTaskCreatePinnedToCore(void (*fn)(void*),const char*,uint32_t,void* arg,int,TaskHandle_t* out,int) {
  int adc=(int)(uintptr_t)arg; if(adc==failTask) return 0;
  auto* t=new FakeTask; *out=t; tasks.push_back(t);
  t->thread=std::thread([=] {current=t; workerAdc=adc; {std::unique_lock<std::mutex> lock(entryMutex);entryCv.wait(lock,[]{return !holdTaskEntry;});} fn(arg);}); return pdPASS;
}
TaskHandle_t xTaskGetCurrentTaskHandle() { return current; }
void vTaskDelay(TickType_t ticks) {
  if(!current && releaseWaiters && !holdWorkers && !holdTaskEntry) {
    // A clean stop explicitly schedules both real worker functions through
    // their RTOS deletion boundary before delivering the next simulated tick.
    // Held-worker/pending-entry cases bypass this and exercise the100ms bound.
    std::unique_lock<std::mutex> lock(exitMutex);
    exitCv.wait(lock,[]{return std::all_of(tasks.begin(),tasks.end(),[](FakeTask* t){return t->exited.load();});});
  }
  delay(ticks);
}
void vTaskDelete(TaskHandle_t) {if(current) {{std::lock_guard<std::mutex> lock(exitMutex);current->exited=true;}exitCv.notify_all();} }
void vTaskNotifyGiveFromISR(TaskHandle_t task,BaseType_t*) { std::lock_guard<std::mutex> lock(task->mutex); ++task->notifications; task->cv.notify_one(); }
uint32_t ulTaskNotifyTake(BaseType_t,TickType_t timeout) {
  if(!current) return 0;
  std::unique_lock<std::mutex> lock(current->mutex);
  if(timeout) current->cv.wait(lock,[&]{return (current->notifications>0 && !holdWorkers) || releaseWaiters;});
  if(holdWorkers && timeout) current->cv.wait(lock,[&]{return !holdWorkers;});
  if(timeout && releaseWaiters && !current->notifications) {
    lock.unlock();delay(timeout);lock.lock();
  }
  unsigned n=current->notifications; current->notifications=0; return n;
}
static void complete(int adc, int count) {
  void (*fn)(void*); void* arg;
  {std::lock_guard<std::mutex> lock(gpioMutex); auto& g=gpio[adc?18:36]; g.level=LOW; fn=g.isr; arg=g.arg;}
  assert(fn);edgeUs[adc]=micros(); for(int i=0;i<count;++i) fn(arg);
}
template<class F> static void await(F pred) { auto until=millis()+1000; while(!pred() && millis()<until) delay(1); assert(pred()); }
static void joinTasks() { for(auto* t:tasks) {t->thread.join(); delete t;} tasks.clear();releaseWaiters=false; }
static void stopAdc_() {
  // Advance simulated missing-DRDY time only when the fixture asks to stop.
  // Normal conversion schedules are notification-driven, independent of host CPU
  // load/timer granularity. Timed public runner cases opt into timeout progress.
  releaseWaiters=true;for(auto* t:tasks){std::lock_guard<std::mutex> lock(t->mutex);t->cv.notify_all();}
  AnalogInputManager::onLoggingStop();
}
static board::BoardProfile adcBoard() {
  return board::GetBoardProfile(board::BoardID::BODAQS_A8);
}

int main() {
  board::SPIProfile bus; bus.present=true; bus.sck=37; bus.miso=39; bus.mosi=38;
  assert(SharedSpiBus::begin(bus));
  SharedSpiBus::probeReset();
  uint8_t tx[256]={0},rx[256];
  for(size_t length: {64U,128U,256U}) assert(SharedSpiBus::transfer(40,SPISettings(16000000,MSBFIRST,SPI_MODE0),tx,rx,length));
  failLock=true;
  assert(!SharedSpiBus::transfer(47,SPISettings(),tx,rx,4));
  failLock=false;
  auto stats=SharedSpiBus::probeSnapshot();
  assert(stats.participant[0].csPin==40 && stats.participant[0].transfers==3 && stats.participant[0].bytes==448);
  assert(stats.participant[0].lockWait.count==3 && stats.participant[0].ownership.count==3);
  assert(stats.participant[1].csPin==47 && stats.participant[1].lockFailures==1 && stats.participant[1].ownership.count==0);
  puts("real SharedSpiBus: geometry, CS serialization and per-CS ownership passed");

  // Actual driver/mutex boundary: zero is a valid CS time; failed lock must not
  // publish a fictitious participant; unselected clocks retire as participant -2.
  SharedSpiBus::probeReset();frozenUs=0;
  SharedSpiBus::ProbeContext firstContext, nextContext;
  assert(SharedSpiBus::transfer(47,SPISettings(1000000,MSBFIRST,SPI_MODE1),tx,rx,4,50,nullptr,nullptr,&firstContext));
  assert(!firstContext.previousValid && firstContext.csAssertUs==0 && firstContext.csReleaseUs==0);
  frozenUs=0xffffffffLL;
  assert(SharedSpiBus::transfer(40,SPISettings(8000000),tx,rx,4,50,nullptr,nullptr,&nextContext));
  assert(nextContext.previousValid && nextContext.previousCs==47 && nextContext.previousReleaseUs==0);
  assert(nextContext.sequence==firstContext.sequence+1);
  auto board=adcBoard();
  assert(SharedSpiBus::probeUnselectedClocks(board.spi));
  frozenUs=3;
  assert(SharedSpiBus::transfer(40,SPISettings(8000000),tx,rx,4,50,nullptr,nullptr,&nextContext));
  assert(nextContext.previousValid && nextContext.previousCs==-2 && nextContext.previousReleaseUs==0xffffffffU);
  frozenUs=-1;
  // Block at the actual RTOS mutex, then retire another participant before the
  // waiting transfer acquires it. Context must describe that committed predecessor.
  sharedSpiLock->lock();std::atomic<bool> finished=false;
  SharedSpiBus::ProbeContext waited;
  std::thread waiter([&]{holdContextAcquisition=true;assert(SharedSpiBus::transfer(40,SPISettings(8000000),tx,rx,4,50,nullptr,nullptr,&waited));finished=true;});
  while(!contextAcquisitionReached)std::this_thread::yield();assert(!finished);
  sharedSpiLock->unlock();
  // The ADC operation commits after the master requested the lock, before the
  // delayed acquisition. Reading predecessor state before lock would miss it.
  assert(SharedSpiBus::transfer(47,SPISettings(1000000,MSBFIRST,SPI_MODE1),tx,rx,4));
  releaseContextAcquisition=true;waiter.join();
  assert(waited.previousValid && waited.previousCs==47 && waited.sequence==nextContext.sequence+2);
  puts("shared bus context: zero and wrapped timestamps, actual unselected mode1 clocks passed");
  AnalogInputManager::begin(board);
  LoggerConfig cfg;cfg.sensorN=2;cfg.sampleRateHz=500;
  for(auto& s:cfg.sensors) {s.type=SensorType::AnalogPot;s.mutedDefault=false;}
  char line0[]="sensor0.ain=0",line1[]="sensor1.ain=4";
  assert(ConfigManager::parseLine(line0,cfg)); assert(ConfigManager::parseLine(line1,cfg));
  assert(AnalogInputManager::configureFromConfig(cfg,500)==500);
  assert(AnalogInputManager::configuredDataRateSps(0)==1000 && AnalogInputManager::configuredDataRateSps(1)==1000);
  AnalogInputManager::onLoggingStart();
  await([]{return AnalogInputManager::probeWorkersRunning();});
  await([]{return starts[0]>=1 && starts[1]>=1;});
  auto row=[] { int32_t a=-1,b=-1;AnalogInputManager::beginSample();assert(AnalogInputManager::readCounts(0,a));assert(AnalogInputManager::readCounts(4,b));AnalogInputManager::endSample();assert(a==0 && b==0); };
  row();auto first=AnalogInputManager::probeLastRow(0);assert(first.valid && first.fresh && first.sequence==1);
  row();assert(!AnalogInputManager::probeLastRow(0).fresh && AnalogInputManager::probeLastRow(0).sequence==1);
  unsigned r0=reads[0];complete(0,2);await([&]{return reads[0]>r0;});await([]{return starts[0]>=2;});
  row();assert(AnalogInputManager::probeLastRow(0).fresh && AnalogInputManager::probeLastRow(0).sequence==2);
  assert(!AnalogInputManager::probeLastRow(4).fresh && AnalogInputManager::probeLastRow(4).sequence==1);
  stopAdc_();assert(AnalogInputManager::probeWorkersStopped());joinTasks();
  auto adc=AnalogInputManager::probeTimingSnapshot();
  assert(adc.adc[0].channel[0].rowFresh==2 && adc.adc[0].channel[0].rowReused==1);
  assert(adc.adc[1].channel[0].rowFresh==1 && adc.adc[1].channel[0].rowReused==2);
  auto drdy=AnalogInputManager::probeDrdySnapshot();
  assert(drdy.adc[0].paired==1 && drdy.adc[0].extra==1);
  assert(drdy.adc[0].toReadAttempt.count==1 && drdy.adc[0].toReadEnd.count==1);
  puts("real ADC: RAM config, equal-valued conversions, repeated cache identities, independent channels, observed DRDY passed");

  assert(AnalogInputManager::configureFromConfig(cfg,500)==500);
  assert(AnalogInputManager::probeDrdySnapshot().adc[0].observed==0);
  for(auto& n:starts) n=0;
  failWarmup=true;
  AnalogInputManager::onLoggingStart();failWarmup=false;
  await([]{return AnalogInputManager::probeWorkersRunning() && starts[0]>=1 && starts[1]>=1;});
  int32_t value;
  AnalogInputManager::beginSample();assert(!AnalogInputManager::readCounts(0,value));AnalogInputManager::endSample();
  assert(!AnalogInputManager::probeLastRow(0).valid);
  r0=reads[0];complete(0);await([&]{return reads[0]>r0;});await([]{return starts[0]>=2;});
  AnalogInputManager::beginSample();assert(AnalogInputManager::readCounts(0,value));AnalogInputManager::endSample();
  assert(AnalogInputManager::probeLastRow(0).sequence==1);
  stopAdc_();assert(AnalogInputManager::probeWorkersStopped());joinTasks();
  assert(AnalogInputManager::probeTimingSnapshot().adc[0].channel[0].rowNoSample==1);
  assert(AnalogInputManager::probeTimingSnapshot().adc[0].waitTimeouts>=1);
  puts("real ADC: failed warmup, no sample, timeout without sequence advance, clean second entry passed");

  AnalogInputManager::configureFromConfig(cfg,500);
  failInterruptRegistration=true;AnalogInputManager::onLoggingStart();
  await([]{return AnalogInputManager::probeWorkersStopped();});
  assert(!AnalogInputManager::probeWorkersRunning());
  {std::lock_guard<std::mutex> lock(gpioMutex);assert(!gpio[18].isr && !gpio[36].isr);}
  stopAdc_();joinTasks();failInterruptRegistration=false;
  puts("ADC interrupt-registration lock failure: no running workers or attached callbacks passed");

  failTask=1;AnalogInputManager::onLoggingStart();delay(2);
  assert(!AnalogInputManager::probeWorkersRunning());
  stopAdc_();assert(AnalogInputManager::probeWorkersStopped());joinTasks();failTask=-1;
  AnalogInputManager::configureFromConfig(cfg,500);
  for(auto& n:starts) n=0;
  holdWorkers=true;AnalogInputManager::onLoggingStart();
  await([]{return starts[0]>=1 && starts[1]>=1;});delay(2);
  stopAdc_();assert(!AnalogInputManager::probeWorkersStopped());
  assert(AnalogInputManager::probeTimingSnapshot().adc[0].channel[0].acquireOk==0);
  holdWorkers=false; for(auto* t:tasks) {std::lock_guard<std::mutex> lock(t->mutex);t->cv.notify_all();}
  await([]{return AnalogInputManager::probeWorkersStopped();});joinTasks();
  puts("real ADC: partial async startup rejection, bounded unfinished stop, no unsafe live snapshot passed");

  AnalogInputManager::configureFromConfig(cfg,500);
  for(auto& n:starts)n=0;
  injectBeforeStart[0]=true;AnalogInputManager::onLoggingStart();
  await([]{return starts[0]>=1 && starts[1]>=1;});
  r0=reads[0];complete(0);await([&]{return reads[0]>r0;});await([]{return starts[0]>=2;});
  // Capture an already-dispatched callback before detach, then let it enter
  // after stopped reset. It must neither write old counters nor target a new task.
  void (*oldIsr)(void*);void* oldArg;
  {std::lock_guard<std::mutex> lock(gpioMutex);oldIsr=gpio[36].isr;oldArg=gpio[36].arg;}
  stopAdc_();assert(AnalogInputManager::probeWorkersStopped());joinTasks();
  drdy=AnalogInputManager::probeDrdySnapshot();
  assert(drdy.adc[0].preStart==1 && drdy.adc[0].paired==1);
  AnalogInputManager::configureFromConfig(cfg,500);
  oldIsr(oldArg);
  assert(AnalogInputManager::probeDrdySnapshot().adc[0].observed==0);
  holdTaskEntry=true;AnalogInputManager::onLoggingStart();
  assert(!AnalogInputManager::probeWorkersRunning() && !AnalogInputManager::probeWorkersStopped());
  stopAdc_();assert(!AnalogInputManager::probeWorkersStopped());
  oldIsr(oldArg);
  {std::lock_guard<std::mutex> lock(entryMutex);holdTaskEntry=false;}entryCv.notify_all();await([]{return AnalogInputManager::probeWorkersStopped();});joinTasks();
  assert(AnalogInputManager::probeDrdySnapshot().adc[0].observed==0);
  puts("real ADC: pre-START lock contention, dispatched ISR after detach/reset, pending-before-entry bounded stop passed");

  AnalogInputManager::configureFromConfig(cfg,500);for(auto& n:starts)n=0;
  delayReadLock[0]=true;AnalogInputManager::onLoggingStart();await([]{return starts[0]>=1 && starts[1]>=1;});
  complete(0);const uint32_t observed=edgeUs[0];await([]{return starts[0]>=2;});
  stopAdc_();assert(AnalogInputManager::probeWorkersStopped());joinTasks();
  drdy=AnalogInputManager::probeDrdySnapshot();
  const uint32_t actualService=static_cast<uint32_t>(readCsUs[0]-observed);
  assert(actualService>=5000 && drdy.adc[0].toReadAttempt.maxUs<actualService);
  // The GPIO injection time precedes observed ISR entry. Do not impose their
  // equality: the independently scripted 5ms lock hold is the lower bound that
  // must be present in successful-return latency and absent from attempt time.
  assert(drdy.adc[0].toReadEnd.count==1 && drdy.adc[0].toReadEnd.maxUs>=5000);
  AnalogInputManager::configureFromConfig(cfg,500);for(auto& n:starts)n=0;
  failReadLock[0]=true;AnalogInputManager::onLoggingStart();await([]{return starts[0]>=1 && starts[1]>=1;});
  row();complete(0);await([]{return starts[0]>=2;});row();
  assert(AnalogInputManager::probeLastRow(0).sequence==1 && !AnalogInputManager::probeLastRow(0).fresh);
  stopAdc_();assert(AnalogInputManager::probeWorkersStopped());joinTasks();
  drdy=AnalogInputManager::probeDrdySnapshot();assert(drdy.adc[0].toReadAttempt.count==1 && drdy.adc[0].toReadEnd.count==0);
  puts("real ADC: contended RDATA attempt versus actual CS service, failed read lock without identity advance passed");

  AnalogInputManager::configureFromConfig(cfg,500);for(auto& n:starts)n=0;
  holdStartTransfer=true;startTransferReached=false;holdTieIsr=true;tieIsrReached=false;
  const int64_t tiedUs=micros();frozenUs=tiedUs;
  AnalogInputManager::onLoggingStart();
  // Wait on hardware-boundary barriers rather than source-private state. ISR
  // entry occurs before START CS high but both observations have the same tick.
  {std::unique_lock<std::mutex> lock(tieMutex);tieCv.wait(lock,[]{return startTransferReached.load();});}
  std::thread oldCallback([]{injectedTieIsr=true;complete(0);});
  {std::unique_lock<std::mutex> lock(tieMutex);tieCv.wait(lock,[]{return tieIsrReached.load();});}
  {std::lock_guard<std::mutex> lock(tieMutex);holdStartTransfer=false;}tieCv.notify_all();
  while(starts[0]<1)std::this_thread::yield();
  {std::lock_guard<std::mutex> lock(tieMutex);holdTieIsr=false;}tieCv.notify_all();oldCallback.join();
  frozenUs=tiedUs+1000;r0=reads[0];complete(0);
  while(starts[0]<2 || reads[0]<=r0)std::this_thread::yield();
  frozenUs=-1;stopAdc_();assert(AnalogInputManager::probeWorkersStopped());joinTasks();
  drdy=AnalogInputManager::probeDrdySnapshot();
  assert(drdy.adc[0].preStart==1 && drdy.adc[0].paired==1 && drdy.adc[0].extra==0);
  puts("real ADC: same-microsecond ISR entry before START marker is ambiguous, later distinct-tick completion paired passed");
#if TEST_CASE_RUNNER
  releaseWaiters=true;
  SpiMeasurementProbe::begin(board);assert(Serial.output.find("spi-probe-v2-")!=std::string::npos);
  puts(Serial.output.c_str());Serial.output.clear();SpiMeasurementProbe::command("status");
  assert(Serial.output.find("\"logger_build\":")!=std::string::npos);puts(Serial.output.c_str());Serial.output.clear();
  // Public runner, deterministic clock boundary: 10 seconds has 5000 midpoints
  // in [start,end). ADC samples remain synthetic; this checks row scheduling,
  // not physical ADC performance or freshness qualification.
  // Hold DRDY low at the GPIO boundary so frozen time cannot strand a real
  // worker in an unexpired conversion wait during STOP. DRDY evidence tests
  // above use real notifications and do not enable this scheduler-only fixture.
  forceReadyPin=true;
  frozenUs=1000000;
  SpiMeasurementProbe::command("case 1 adc 128 8000000 1 10000");
  assert(Serial.output.empty());
  for(unsigned row=0;row<5000;++row) {
    frozenUs=1001000+row*2000;SpiMeasurementProbe::loop();
  }
  assert(Serial.output.empty());
  frozenUs=11000000;SpiMeasurementProbe::loop();joinTasks();
  assert(Serial.output.find("\"rows\":5000,\"missed_rows\":0")!=std::string::npos);
  puts(Serial.output.c_str());Serial.output.clear();
  releaseWaiters=true;frozenUs=12000000;
  SpiMeasurementProbe::command("case 2 adc 128 8000000 1 100");
  for(unsigned row=0;row<50;++row) {
    if(row==10)continue; // An actual skipped midpoint must remain a miss.
    frozenUs=12001000+row*2000;SpiMeasurementProbe::loop();
  }
  frozenUs=12100000;SpiMeasurementProbe::loop();joinTasks();
  assert(Serial.output.find("\"rows\":49,\"missed_rows\":1")!=std::string::npos);
  puts(Serial.output.c_str());Serial.output.clear();
  releaseWaiters=true;frozenUs=13000000;
  SpiMeasurementProbe::command("case 3 adc 128 8000000 1 100");
  frozenUs=13001000;SpiMeasurementProbe::loop();
  frozenUs=13004500;SpiMeasurementProbe::command("stop");joinTasks();
  assert(Serial.output.find("\"rows\":1,\"missed_rows\":1")!=std::string::npos);
  puts(Serial.output.c_str());Serial.output.clear();
  releaseWaiters=true;frozenUs=14000000;
  SpiMeasurementProbe::command("case 4 adc 128 8000000 1 100");
  frozenUs=14110000;SpiMeasurementProbe::loop();joinTasks();frozenUs=-1;forceReadyPin=false;
  assert(Serial.output.find("\"rows\":0,\"missed_rows\":50")!=std::string::npos);
  puts(Serial.output.c_str());Serial.output.clear();releaseWaiters=true;
  puts("public runner: 5000 midpoint rows without endpoint miss, genuine skip, finite early STOP and late completion passed");
  SpiMeasurementProbe::command("case 5 adc 128 16000000 2 100");
  assert(Serial.output.empty());
  SpiMeasurementProbe::command("case 6 adc 256 16000000 4 100");assert(Serial.output.empty());
  // Scheduling delayed past several deadlines consumes one row, not repeated
  // catch-up cache reads. The public result must retain exactly 50 row slots.
  delay(11);SpiMeasurementProbe::loop();
  delay(110);SpiMeasurementProbe::loop();joinTasks();
  assert(Serial.output.find("\"rows\":1,\"missed_rows\":49")!=std::string::npos);
  assert(Serial.output.find("\"commands\":1")!=std::string::npos);
  assert(Serial.output.find("\"frame_bytes\":128")!=std::string::npos);
  assert(Serial.output.find("\"outcome\":\"complete\"")!=std::string::npos);
  assert(std::count(Serial.output.begin(),Serial.output.end(),'\n')==1);
  puts(Serial.output.c_str());Serial.output.clear();
  SpiMeasurementProbe::command("case -1 adc 64 8000000 1 100");
  assert(Serial.output.find("invalid_profile")!=std::string::npos);
  puts("public probe command/result: fixed profile, suppressed timed serial, missed deadlines, one bounded summary passed");
  Serial.output.clear();railFault=true;
  SpiMeasurementProbe::command("case 6 mixed 64 8000000 4 100");railFault=false;
  assert(Serial.output.find("analog_rail_fault")!=std::string::npos && Serial.output.find("\"slots\":0")!=std::string::npos);
  puts(Serial.output.c_str());
  Serial.output.clear();failTask=1;releaseWaiters=true;
  SpiMeasurementProbe::command("case 7 adc 64 8000000 1 100");failTask=-1;joinTasks();
  assert(Serial.output.find("async_start_failed")!=std::string::npos && Serial.output.find("\"workers_stopped\":true")!=std::string::npos);
  Serial.output.clear();releaseWaiters=true;
  SpiMeasurementProbe::command("case 8 adc 64 8000000 1 1000");delay(11);SpiMeasurementProbe::command("stop");joinTasks();
  assert(Serial.output.find("\"outcome\":\"stopped\"")!=std::string::npos && Serial.output.find("\"rows\":0,\"missed_rows\":0")==std::string::npos);
  puts("public probe: rail fault and async startup failures, stopped workers before new case, early STOP records missed deadlines passed");
  Serial.output.clear();SpiMeasurementProbe::command("case 8 adc 64 8000000 1 1000");
  assert(Serial.output.find("non_increasing_case_id")!=std::string::npos && AnalogInputManager::probeWorkersStopped());
  Serial.output.clear();SpiMeasurementProbe::command("case 7 adc 64 8000000 1 1000");
  assert(Serial.output.find("non_increasing_case_id")!=std::string::npos);
  puts("public probe: reused and older IDs including prior failed starts rejected before hardware work passed");
  masterEnabled=true;bodaqs_spi_probe_init(&master);
  Serial.output.clear();SpiMeasurementProbe::command("case 9 bulk 256 16000000 4 100");
  while(Serial.output.empty())SpiMeasurementProbe::loop();
  assert(Serial.output.find("\"mode\":\"bulk\"")!=std::string::npos && Serial.output.find("\"rows\":0")!=std::string::npos);
  assert(Serial.output.find("\"accepted_bytes\":0")==std::string::npos && AnalogInputManager::probeWorkersStopped());
  puts(Serial.output.c_str());
  Serial.output.clear();releaseWaiters=true;SpiMeasurementProbe::command("case 10 mixed 128 8000000 4 100");
  while(Serial.output.empty())SpiMeasurementProbe::loop();joinTasks();
  assert(Serial.output.find("\"mode\":\"mixed\"")!=std::string::npos && Serial.output.find("\"accepted_bytes\":0")==std::string::npos);
  assert(Serial.output.find("\"measured\":true")!=std::string::npos);
  puts(Serial.output.c_str());
  puts("public bulk/mixed cases: actual client+engine traffic, shared ADC path, stopped profile changes, one result each passed");
  Serial.output.clear();SpiMeasurementProbe::command("case 11 bulk 128 8000000 1 100");
  master.active=false;
  while(Serial.output.empty())SpiMeasurementProbe::loop();
  assert(Serial.output.find("\"outcome\":\"failed\"")!=std::string::npos && Serial.output.find("bulk_fault_or_stalled")!=std::string::npos && Serial.output.find("\"accept\":1")!=std::string::npos);
  puts(Serial.output.c_str());
  puts("public short bulk case: actual same-case peer ERROR produces failed result without waiting for stall duration passed");
  Serial.output.clear();const unsigned switchBefore=syntheticSwitchCount;
  SpiMeasurementProbe::command("case 12 switch 128 8000000 4 100 cached 500");
  SpiMeasurementProbe::command("case 13 bulk 256 16000000 1 100 legacy 0"); // immutable active profile
  while(Serial.output.empty())SpiMeasurementProbe::loop();
  assert(Serial.output.find("\"mode\":\"switch\"")!=std::string::npos && AnalogInputManager::probeWorkersStopped());
  assert(syntheticSwitchCount>switchBefore && SpiProbeTransport::stats().switchTransfers>0);
  assert(SpiProbeTransport::stats().requestInterval.minUs>=500);
  puts(Serial.output.c_str());Serial.output.clear();releaseWaiters=true;
  SpiMeasurementProbe::command("case 13 mixed 128 8000000 4 100 cached 5000");
  while(Serial.output.empty())SpiMeasurementProbe::loop();joinTasks();
  assert(SpiProbeTransport::stats().pacingDeferred>0 && SpiProbeTransport::stats().requestInterval.minUs>=5000);
  puts(Serial.output.c_str());Serial.output.clear();
  SpiMeasurementProbe::command("case 14 bulk 128 8000000 1 100 legacy 0");rawFault=3;rawFaultsLeft=8;
  while(Serial.output.empty())SpiMeasurementProbe::loop();
  assert(SpiProbeTransport::stats().wireErrors==8 && SpiProbeTransport::stats().failureCount==4 && SpiProbeTransport::stats().failureSamplesOmitted==4);
  puts(Serial.output.c_str());Serial.output.clear();
  SpiMeasurementProbe::command("case 14 adc 128 8000000 1 100 cached 5001");
  assert(Serial.output.find("invalid_profile")!=std::string::npos);Serial.output.clear();
  SpiMeasurementProbe::command("case 14 adc 128 8000000 1 100 cached 0");
  assert(Serial.output.find("non_increasing_case_id")!=std::string::npos);Serial.output.clear();
  puts("public extended controls: immutable switch/cached/paced profiles, ADC row budget while deferred, bounded raw failure JSON passed");
  uint32_t caseId=15;
  for(uint16_t frame: {64,128,256})for(uint32_t hz: {8000000U,16000000U}) {
    assert(SpiProbeTransport::begin(board,caseId++,frame,hz,4));
    for(unsigned attempts=0;attempts<1000000 && SpiProbeTransport::stats().retiredObjects<4;++attempts)SpiProbeTransport::tick();
    assert(SpiProbeTransport::stats().uniqueObjects==4 && SpiProbeTransport::stats().acceptedBytes==4032 && SpiProbeTransport::stats().retiredObjects==4);
    assert(SpiProbeTransport::stop());
    assert(SpiProbeTransport::stats().masterMeasured);
  }
  puts("real SPI/client/engine: all six profiles, delayed replies, exact unique1008-byte objects, RAM ACK retirement, confirmed STOP passed");
  assert(SpiProbeTransport::begin(board,caseId++,128,8000000,1));
  master.active=false; // Actual peer now emits response ERROR=255, not stale data.
  for(unsigned attempts=0;attempts<100000 && SpiProbeTransport::healthy();++attempts)SpiProbeTransport::tick();
  assert(!SpiProbeTransport::healthy() && SpiProbeTransport::stats().acceptErrors==1 && SpiProbeTransport::stats().acceptedBytes==0);
  assert(SpiProbeTransport::stop());
  puts("real client/engine: explicit same-case peer ERROR terminates immediately before short-case duration passed");
  assert(SpiProbeTransport::begin(board,caseId++,256,16000000,1));corruptPayload=true;
  for(unsigned attempts=0;attempts<100000 && !SpiProbeTransport::stats().acceptErrors;++attempts)SpiProbeTransport::tick();
  assert(SpiProbeTransport::stats().acceptErrors==1 && SpiProbeTransport::stats().acceptedBytes==0 && SpiProbeTransport::stats().retiredObjects==0);
  assert(SpiProbeTransport::stop());
  // Actual raw rejection provenance: eight failures saturate four fixed slots,
  // transfer failures never invoke decoding, and a new case clears all samples.
  for(unsigned reason=3;reason<=8;++reason) {
    assert(SpiProbeTransport::begin(board,caseId++,128,8000000,1));
    injectedRx.clear();rawFault=reason;rawFaultsLeft=8;
    for(unsigned attempts=0;attempts<100000 && rawFaultsLeft;++attempts)SpiProbeTransport::tick();
    const auto& d=SpiProbeTransport::stats();
    assert(rawFaultsLeft==0 && d.wireErrors==8 && d.decodeCounts[reason]==8);
    assert(d.failureCount==4 && d.failureSamplesOmitted==4);
    for(unsigned i=0;i<4;++i) {
      const auto& f=d.failures[i];assert(f.reason==reason && f.slot==i+1 && f.frameBytes==128);
      assert(f.caseId==caseId-1 && f.objectId==1 && f.opcode==BODAQS_PROBE_POLL);
      assert(f.bus.cs==40 && f.bus.previousValid && f.bus.previousCs==40);
      assert(memcmp(f.rx,injectedRx[i].data(),128)==0);
      if(reason==3)assert(f.rx[0]==0);
    }
    assert(d.byPreviousCs[0].responses==0 && d.byPreviousCs[0].decodeFailures==8);
    assert(SpiProbeTransport::stop());
  }
  assert(SpiProbeTransport::begin(board,caseId++,128,8000000,1));
  assert(SpiProbeTransport::stats().failureCount==0 && SpiProbeTransport::stats().failureSamplesOmitted==0);
  failLock=true;for(unsigned attempts=0;attempts<100000 && !SpiProbeTransport::stats().transferErrors;++attempts)SpiProbeTransport::tick();failLock=false;
  assert(SpiProbeTransport::stats().transferErrors==1 && SpiProbeTransport::stats().decode.count==0);
  assert(SpiProbeTransport::stop());
  puts("raw reply failures: each wire reason, complete bounded samples, omission counts, reset and transfer/decode separation passed");

  // CRC controls retain exact-byte, whole-object validation and ACK safety.
  for(auto mode:{SpiProbeTransport::CrcMode::Legacy,SpiProbeTransport::CrcMode::Cached}) {
    assert(SpiProbeTransport::begin(board,caseId++,128,8000000,2,mode));
    for(unsigned attempts=0;attempts<1000000 && SpiProbeTransport::stats().retiredObjects<4;++attempts)SpiProbeTransport::tick();
    const auto& d=SpiProbeTransport::stats();assert(d.retiredObjects==4 && d.acceptedBytes==4032);
    if(mode==SpiProbeTransport::CrcMode::Cached)assert(d.expectedCrc.count==4);
    else assert(d.expectedCrc.count>4);
    assert(SpiProbeTransport::stop());
    assert(SpiProbeTransport::begin(board,caseId++,256,16000000,1,mode));corruptPayload=true;
    for(unsigned attempts=0;attempts<100000 && SpiProbeTransport::healthy();++attempts)SpiProbeTransport::tick();
    assert(SpiProbeTransport::stats().acceptErrors==1 && SpiProbeTransport::stats().acceptedBytes==0 && SpiProbeTransport::stats().retiredObjects==0);
    assert(SpiProbeTransport::stop());
  }
  puts("legacy/cached CRC: two-node object turnover, per-object expected CRC, corrupted exact bytes and ACK safety passed");

  stats2Unsupported=true;const auto unsupportedBegan=micros();
  assert(SpiProbeTransport::begin(board,caseId++,128,8000000,1));
  assert(micros()-unsupportedBegan<100000); // explicit ERROR is promptly unknown
  assert(SpiProbeTransport::stats().slots==0 && SpiProbeTransport::stats().decode.count==0);
  assert(SpiProbeTransport::stop() && !SpiProbeTransport::stats().diagnosticMeasured);
  assert(SpiProbeTransport::stats().masterMeasured && SpiProbeTransport::stats().adapterMeasured);
  stats2Unsupported=false;
  puts("master STATS2: unsupported explicit response remains promptly unknown, page0/1 and controls retain separate scopes passed");

  // Freeze only active iterations: control entry/STOP use real advancing clock.
  assert(SpiProbeTransport::begin(board,caseId++,128,8000000,1,SpiProbeTransport::CrcMode::Cached,5000,true));
  frozenUs=static_cast<int64_t>(micros())+10000;
  SpiProbeTransport::tick();const auto slots=SpiProbeTransport::stats().slots;
  for(unsigned i=0;i<100;++i)SpiProbeTransport::tick();
  assert(SpiProbeTransport::stats().slots==slots && SpiProbeTransport::stats().pacingDeferred>=100);
  frozenUs+=5000;SpiProbeTransport::tick(); // unselected control, never a master slot
  assert(SpiProbeTransport::stats().switchTransfers==1 && SpiProbeTransport::stats().slots==slots);
  SpiProbeTransport::tick();
  assert(SpiProbeTransport::stats().slots==slots+1 && SpiProbeTransport::stats().requestInterval.minUs>=5000);
  assert(SpiProbeTransport::stats().byPreviousCs[1].cs==-2);
  frozenUs+=5000;failLock=true;SpiProbeTransport::tick();failLock=false;
  assert(SpiProbeTransport::stats().switchFailures==1 && !SpiProbeTransport::healthy());
  frozenUs=-1;bulkLastHigh=0;assert(SpiProbeTransport::stop());
  puts("nonblocking pacing: deferred iterations, synthetic all-CS-high clocks, actual interval and preceding -2 context passed");

  assert(SpiProbeTransport::begin(board,caseId++,128,8000000,1));masterSilent=true;
  assert(!SpiProbeTransport::stop());assert(!SpiProbeTransport::begin(board,caseId++,64,8000000,1));
  puts("real client: valid-wire corrupted logical bytes never accepted/ACKed; unconfirmed STOP blocks profile changes passed");
#endif
}
