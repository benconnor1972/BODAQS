#include <cassert>
#include <cstdio>
#include <functional>
#include <vector>
#include <array>
#include <atomic>
#include "AnalogInputManager.h"
#include "SharedSpiBus.h"
#include "AdcReadyWait.h"
#include "ConfigManager.h"
#include "Rates.h"

constexpr int LOW=0, HIGH=1, INPUT=0, INPUT_PULLUP=2, OUTPUT=3, FALLING=4, RISING=5;
uint32_t nowUs = 100;
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
constexpr uint32_t configTICK_RATE_HZ=1000;
constexpr int configMAX_PRIORITIES=25;
#define pdMS_TO_TICKS(ms) (ms)
#define portENTER_CRITICAL(m) ((void)(m))
#define portEXIT_CRITICAL(m) ((void)(m))
#define portENTER_CRITICAL_ISR(m) ((void)(m))
#define portEXIT_CRITICAL_ISR(m) ((void)(m))
#define portYIELD_FROM_ISR() ((void)0)
TaskHandle_t xTaskGetCurrentTaskHandle() { return reinterpret_cast<void*>(1); }
void vTaskNotifyGiveFromISR(TaskHandle_t, BaseType_t*) {}
unsigned clears=0;
uint32_t ulTaskNotifyTake(int, TickType_t ticks) {
  if (!ticks) ++clears;
  nowUs += ticks*1000; return 0;
}
void vTaskDelay(TickType_t ticks) { nowUs += ticks*1000; }
void vTaskDelete(TaskHandle_t) {}
void attachInterruptArg(uint8_t, void (*)(void*), void*, int) {}
void detachInterrupt(uint8_t) {}
unsigned failCreateAdc=4;
int xTaskCreatePinnedToCore(void (*)(void*), const char*, uint32_t, void* argument, int priority,
                            TaskHandle_t* handle, int core) {
  assert(priority==ADC_TEST_EXPECTED_PRIORITY);
  assert(core==0);
  if(reinterpret_cast<uintptr_t>(argument)==failCreateAdc) return pdFALSE;
  *handle=xTaskGetCurrentTaskHandle(); return pdPASS;
}
#endif

// PRODUCTION_MANAGER

struct AdcModel {
  std::array<uint8_t,4> regs{};
  unsigned starts=0, reads=0, readyAt=0, generation=0;
  bool active=false;
  bool timeout=false;
};
AdcModel chips[2];
struct Transaction { int cs; std::vector<uint8_t> bytes; };
std::vector<Transaction> wire;
int failCommand=-1;
bool completeDuringWrite=false;
unsigned clearCountAtWrite=0;
std::function<void()> afterRead;
namespace SharedSpiBus {
bool begin(const board::SPIProfile&) { return true; }
bool transfer(int8_t cs, const SPISettings&, const uint8_t* tx, uint8_t* rx,
              size_t len, uint32_t, uint32_t, uint32_t csSetupUs,SpiTransactionContext* context,SpiTransferTiming* timing) {
  if(context) *context={};
  if(timing) {timing->lockWaitUs=17;timing->prepareUs=11;timing->transferUs=48;timing->finishUs=7;}
  assert(csSetupUs==0); // CAN experiment must not delay the ADC.
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
    assert((chip.regs[1]&0x04)==0x04);
    // Do not require WREG alone to wake/start a conversion. Exercise both
    // behaviors; the r1 hardware test failed when explicit START was removed.
    if (ADC_TEST_WREG_STARTS) {
      chip.active=true; ++chip.generation;
      chip.readyAt=nowUs+(completeDuringWrite?0:40);
    }
    if (len==count+2) {
      assert(tx[count+1]==0x08); // decoder resumes after the WREG payload
      ++chip.starts; ++chip.generation; chip.active=true;
      chip.readyAt=nowUs+(completeDuringWrite?0:40);
    }
  } else if(cmd==0x23) {
    assert(len==9 && tx[5]==0x10 && chip.active && !chip.timeout && nowUs>=chip.readyAt);
    for(unsigned i=0;i<4;++i)rx[i+1]=chip.regs[i];
    // Deliberately identical values across distinct conversions.
    rx[6]=1;rx[7]=2;rx[8]=3;++chip.reads;
    chip.readyAt=nowUs+1000;
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
 auto p=profile();AnalogInputManager::begin(p);
 LoggerConfig cfg;ParamStore params[2];cfg.sensorN=2;
 for(unsigned i=0;i<2;++i){assert(params[i].set("ain",i?"4":"0"));cfg.sensors[i].type=SensorType::AnalogPot;cfg.sensors[i].params.bind(&params[i]);}
 auto start=[&](){chips[0].timeout=chips[1].timeout=false;assert(AnalogInputManager::configureFromConfig(cfg,500)==500);wire.clear();AnalogInputManager::onLoggingStart();};
 start();assert(AnalogInputManager::continuousHealthy());assert(AnalogInputManager::stoppedTimingStats()==nullptr);assert(commands(0x43)==2 && commands(0x23)==2);
 for(unsigned a=0;a<2;++a){assert(chips[a].starts==1 && chips[a].regs[1]==0xc4);assert(AnalogInputManager::timingStats().adc[a].continuousRunning);}
 wire.clear();nowUs+=2000;AnalogInputManager::beginSample();int32_t first=read(0);read(4);AnalogInputManager::endSample();
 assert(commands(0x43)==0 && commands(0x23)==2 && wire.size()==2);
 auto sequence=s_ads[0].cachedSeq[0];nowUs+=2000;AnalogInputManager::beginSample();assert(read(0)==first);read(4);AnalogInputManager::endSample();assert(s_ads[0].cachedSeq[0]>sequence);
 // No new data: reuse without any SPI read or fabricated fresh sequence.
 chips[0].readyAt=chips[1].readyAt=nowUs+3000;wire.clear();sequence=s_ads[0].cachedSeq[0];AnalogInputManager::beginSample();assert(read(0)==first);read(4);AnalogInputManager::endSample();
 assert(wire.empty() && s_ads[0].cachedSeq[0]==sequence && AnalogInputManager::timingStats().adc[0].channel[0].rowReused==1);
 // A conversion completed during the last read remains available to the next.
 nowUs+=4000;afterRead=[&](){chips[0].readyAt=nowUs;};AnalogInputManager::beginSample();read(0);read(4);AnalogInputManager::endSample();afterRead={};assert(AnalogInputManager::continuousHealthy());
 // Stalled ADC cannot be silently read forever.
 nowUs+=11000;chips[0].timeout=true;AnalogInputManager::beginSample();AnalogInputManager::endSample();assert(!AnalogInputManager::continuousHealthy());assert(AnalogInputManager::timingStats().adc[0].continuousStalls==1);
 AnalogInputManager::onLoggingStop();assert(!chips[0].active && !chips[1].active);assert(!AnalogInputManager::timingStats().adc[0].continuousRunning);assert(AnalogInputManager::stoppedTimingStats());
 // Wrong mux/gain/mode/rate/reference image: no publication, fail closed.
 for(unsigned reg=0;reg<4;++reg){start();assert(AnalogInputManager::continuousHealthy());sequence=s_ads[0].cachedSeq[0];chips[0].regs[reg]^=1;nowUs+=2000;AnalogInputManager::beginSample();AnalogInputManager::endSample();assert(!AnalogInputManager::continuousHealthy());assert(s_ads[0].cachedSeq[0]==sequence);assert(AnalogInputManager::timingStats().adc[0].continuousConfigFaults==1);AnalogInputManager::onLoggingStop();}
 start();sequence=s_ads[0].cachedSeq[0];failCommand=0x23;nowUs+=2000;AnalogInputManager::beginSample();AnalogInputManager::endSample();assert(!AnalogInputManager::continuousHealthy() && s_ads[0].cachedSeq[0]==sequence);AnalogInputManager::onLoggingStop();
 // Partial startup and explicit START failure retire both devices.
 AnalogInputManager::configureFromConfig(cfg,500);failCommand=0x43;AnalogInputManager::onLoggingStart();assert(!AnalogInputManager::continuousHealthy());AnalogInputManager::onLoggingStop();
 start();assert(AnalogInputManager::continuousHealthy());failCommand=0x02;AnalogInputManager::onLoggingStop();assert(AnalogInputManager::timingStats().adc[0].continuousStopFailures==1);
 assert(params[1].set("ain","1"));AnalogInputManager::configureFromConfig(cfg,500);wire.clear();AnalogInputManager::onLoggingStart();assert(!AnalogInputManager::continuousHealthy() && wire.empty());AnalogInputManager::onLoggingStop();
 assert(params[1].set("ain","4"));start();assert(AnalogInputManager::continuousHealthy());AnalogInputManager::onLoggingStop();
 puts("Continuous latest actual manager: CM/START once, combined verified read, identical-value freshness, no-new reuse, ready race, stalled/reset/config-fault rejection, transfer/partial-start/STOP failure, unsupported scope and restart PASS");
}
