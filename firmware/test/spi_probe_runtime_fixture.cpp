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
#include <cstdarg>
#if TEST_CASE_RUNNER
#include "SpiMeasurementProbe.h"
#endif
// CONFIG_SUPPORT

static const auto epoch = std::chrono::steady_clock::now();
unsigned long micros() { return (unsigned long)std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now()-epoch).count(); }
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
void digitalWrite(uint8_t pin,uint8_t level) { if (level==LOW) { assert(selected.exchange(pin)==-1); if(workerAdc>=0 && workerLockCalls==3)readCsUs[workerAdc]=micros(); } else if(selected==pin) selected=-1; }
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
  if(adc>=0 && tx && tx[0]==8) {
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
struct FakeTask { std::thread thread; std::mutex mutex; std::condition_variable cv; unsigned notifications=0; };
static thread_local FakeTask* current=nullptr;
static std::vector<FakeTask*> tasks;
static int failTask=-1;
static std::atomic<bool> holdWorkers=false;
static std::atomic<bool> holdTaskEntry=false;
static std::mutex entryMutex;
static std::condition_variable entryCv;
BaseType_t xTaskCreatePinnedToCore(void (*fn)(void*),const char*,uint32_t,void* arg,int,TaskHandle_t* out,int) {
  int adc=(int)(uintptr_t)arg; if(adc==failTask) return 0;
  auto* t=new FakeTask; *out=t; tasks.push_back(t);
  t->thread=std::thread([=] {current=t; workerAdc=adc; {std::unique_lock<std::mutex> lock(entryMutex);entryCv.wait(lock,[]{return !holdTaskEntry;});} fn(arg);}); return pdPASS;
}
TaskHandle_t xTaskGetCurrentTaskHandle() { return current; }
void vTaskDelay(TickType_t ticks) { delay(ticks); }
void vTaskDelete(TaskHandle_t) {}
void vTaskNotifyGiveFromISR(TaskHandle_t task,BaseType_t*) { std::lock_guard<std::mutex> lock(task->mutex); ++task->notifications; task->cv.notify_one(); }
uint32_t ulTaskNotifyTake(BaseType_t,TickType_t timeout) {
  if(!current) return 0;
  std::unique_lock<std::mutex> lock(current->mutex);
  if(timeout) current->cv.wait_for(lock,std::chrono::milliseconds(timeout),[&]{return current->notifications>0 && !holdWorkers;});
  if(holdWorkers && timeout) current->cv.wait(lock,[&]{return !holdWorkers;});
  unsigned n=current->notifications; current->notifications=0; return n;
}
static void complete(int adc, int count) {
  void (*fn)(void*); void* arg;
  {std::lock_guard<std::mutex> lock(gpioMutex); auto& g=gpio[adc?18:36]; g.level=LOW; fn=g.isr; arg=g.arg;}
  assert(fn);edgeUs[adc]=micros(); for(int i=0;i<count;++i) fn(arg);
}
template<class F> static void await(F pred) { auto until=millis()+1000; while(!pred() && millis()<until) delay(1); assert(pred()); }
static void joinTasks() { for(auto* t:tasks) {t->thread.join(); delete t;} tasks.clear(); }
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
  AnalogInputManager::onLoggingStop();assert(AnalogInputManager::probeWorkersStopped());joinTasks();
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
  AnalogInputManager::onLoggingStop();assert(AnalogInputManager::probeWorkersStopped());joinTasks();
  assert(AnalogInputManager::probeTimingSnapshot().adc[0].channel[0].rowNoSample==1);
  assert(AnalogInputManager::probeTimingSnapshot().adc[0].waitTimeouts>=1);
  puts("real ADC: failed warmup, no sample, timeout without sequence advance, clean second entry passed");

  AnalogInputManager::configureFromConfig(cfg,500);
  failTask=1;AnalogInputManager::onLoggingStart();delay(2);
  assert(!AnalogInputManager::probeWorkersRunning());
  AnalogInputManager::onLoggingStop();assert(AnalogInputManager::probeWorkersStopped());joinTasks();failTask=-1;
  AnalogInputManager::configureFromConfig(cfg,500);
  for(auto& n:starts) n=0;
  holdWorkers=true;AnalogInputManager::onLoggingStart();
  await([]{return starts[0]>=1 && starts[1]>=1;});delay(2);
  AnalogInputManager::onLoggingStop();assert(!AnalogInputManager::probeWorkersStopped());
  assert(AnalogInputManager::probeTimingSnapshot().adc[0].channel[0].acquireOk==0);
  holdWorkers=false; for(auto* t:tasks) t->cv.notify_all();
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
  AnalogInputManager::onLoggingStop();assert(AnalogInputManager::probeWorkersStopped());joinTasks();
  drdy=AnalogInputManager::probeDrdySnapshot();
  assert(drdy.adc[0].preStart==1 && drdy.adc[0].paired==1);
  AnalogInputManager::configureFromConfig(cfg,500);
  oldIsr(oldArg);
  assert(AnalogInputManager::probeDrdySnapshot().adc[0].observed==0);
  holdTaskEntry=true;AnalogInputManager::onLoggingStart();
  assert(!AnalogInputManager::probeWorkersRunning() && !AnalogInputManager::probeWorkersStopped());
  AnalogInputManager::onLoggingStop();assert(!AnalogInputManager::probeWorkersStopped());
  oldIsr(oldArg);
  holdTaskEntry=false;entryCv.notify_all();await([]{return AnalogInputManager::probeWorkersStopped();});joinTasks();
  assert(AnalogInputManager::probeDrdySnapshot().adc[0].observed==0);
  puts("real ADC: pre-START lock contention, dispatched ISR after detach/reset, pending-before-entry bounded stop passed");

  AnalogInputManager::configureFromConfig(cfg,500);for(auto& n:starts)n=0;
  delayReadLock[0]=true;AnalogInputManager::onLoggingStart();await([]{return starts[0]>=1 && starts[1]>=1;});
  complete(0);const uint32_t observed=edgeUs[0];await([]{return starts[0]>=2;});
  AnalogInputManager::onLoggingStop();assert(AnalogInputManager::probeWorkersStopped());joinTasks();
  drdy=AnalogInputManager::probeDrdySnapshot();
  const uint32_t actualService=static_cast<uint32_t>(readCsUs[0]-observed);
  assert(actualService>=5000 && drdy.adc[0].toReadAttempt.maxUs<actualService);
  assert(drdy.adc[0].toReadEnd.count==1 && drdy.adc[0].toReadEnd.maxUs>=actualService);
  AnalogInputManager::configureFromConfig(cfg,500);for(auto& n:starts)n=0;
  failReadLock[0]=true;AnalogInputManager::onLoggingStart();await([]{return starts[0]>=1 && starts[1]>=1;});
  row();complete(0);await([]{return starts[0]>=2;});row();
  assert(AnalogInputManager::probeLastRow(0).sequence==1 && !AnalogInputManager::probeLastRow(0).fresh);
  AnalogInputManager::onLoggingStop();assert(AnalogInputManager::probeWorkersStopped());joinTasks();
  drdy=AnalogInputManager::probeDrdySnapshot();assert(drdy.adc[0].toReadAttempt.count==1 && drdy.adc[0].toReadEnd.count==0);
  puts("real ADC: contended RDATA attempt versus actual CS service, failed read lock without identity advance passed");
#if TEST_CASE_RUNNER
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
#endif
}
