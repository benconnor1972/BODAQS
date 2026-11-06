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
void digitalWrite(uint8_t pin,uint8_t level) { if (level==LOW) { assert(selected.exchange(pin)==-1); if(workerAdc>=0 && workerLockCalls==3)readCsUs[workerAdc]=micros();
#if TEST_CASE_RUNNER
  if(pin==40 && masterEnabled && bulkLastHigh)assert(esp_timer_get_time()-bulkLastHigh>=25);
#endif
  } else if(selected==pin) {
#if TEST_CASE_RUNNER
    if(pin==40 && masterEnabled)bulkLastHigh=esp_timer_get_time();
#endif
    selected=-1;
  } }
int digitalRead(uint8_t pin) { std::lock_guard<std::mutex> lock(gpioMutex); return gpio[pin].level; }
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
  assert(selected>=0); delayMicroseconds(10); if(rx) memset(rx,0,length);
  const int adc=selected==47?0:selected==21?1:-1;
  if(adc>=0)assert(settings.hz==1000000 && settings.mode==SPI_MODE1);
  if(selected==40)assert((settings.hz==16000000 || settings.hz==8000000) && settings.mode==SPI_MODE0);
#if TEST_CASE_RUNNER
  if(selected==40 && masterEnabled) {
    if(rx)memcpy(rx,replies.front().data(),length);replies.pop_front();
    std::array<uint8_t,256> prepared{};
    if(!masterSilent)bodaqs_spi_probe_process(&master,tx,length,prepared.data(),prepared.size());
    BodaqsSpiProbeFrame response;
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
SemaphoreHandle_t xSemaphoreCreateMutex() { return new std::timed_mutex; }
static std::atomic<bool> failLock=false,failWarmup=false;
BaseType_t xSemaphoreTake(SemaphoreHandle_t m,TickType_t timeout) {
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

  auto board=adcBoard();
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
  SpiMeasurementProbe::begin(board);Serial.output.clear();
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
  uint32_t caseId=12;
  for(uint16_t frame: {64,128,256})for(uint32_t hz: {8000000U,16000000U}) {
    assert(SpiProbeTransport::begin(board,caseId++,frame,hz,4));
    for(unsigned attempts=0;attempts<3000 && SpiProbeTransport::stats().retiredObjects<4;++attempts)SpiProbeTransport::tick();
    assert(SpiProbeTransport::stats().uniqueObjects==4 && SpiProbeTransport::stats().acceptedBytes==4032 && SpiProbeTransport::stats().retiredObjects==4);
    assert(SpiProbeTransport::stop());
    assert(SpiProbeTransport::stats().masterMeasured);
  }
  puts("real SPI/client/engine: all six profiles, delayed replies, exact unique1008-byte objects, RAM ACK retirement, confirmed STOP passed");
  assert(SpiProbeTransport::begin(board,caseId++,128,8000000,1));
  master.active=false; // Actual peer now emits response ERROR=255, not stale data.
  for(unsigned attempts=0;attempts<30 && SpiProbeTransport::healthy();++attempts)SpiProbeTransport::tick();
  assert(!SpiProbeTransport::healthy() && SpiProbeTransport::stats().acceptErrors==1 && SpiProbeTransport::stats().acceptedBytes==0);
  assert(SpiProbeTransport::stop());
  puts("real client/engine: explicit same-case peer ERROR terminates immediately before short-case duration passed");
  assert(SpiProbeTransport::begin(board,caseId++,256,16000000,1));corruptPayload=true;
  for(unsigned attempts=0;attempts<100 && !SpiProbeTransport::stats().acceptErrors;++attempts)SpiProbeTransport::tick();
  assert(SpiProbeTransport::stats().acceptErrors==1 && SpiProbeTransport::stats().acceptedBytes==0 && SpiProbeTransport::stats().retiredObjects==0);
  assert(SpiProbeTransport::stop());
  assert(SpiProbeTransport::begin(board,caseId++,128,8000000,1));masterSilent=true;
  assert(!SpiProbeTransport::stop());assert(!SpiProbeTransport::begin(board,caseId++,64,8000000,1));
  puts("real client: valid-wire corrupted logical bytes never accepted/ACKed; unconfirmed STOP blocks profile changes passed");
#endif
}
