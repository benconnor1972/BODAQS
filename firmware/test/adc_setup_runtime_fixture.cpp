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
int xTaskCreatePinnedToCore(void (*)(void*), const char*, uint32_t, void* argument, int,
                            TaskHandle_t* handle, int) {
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
              size_t len, uint32_t, uint32_t, uint32_t csSetupUs) {
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
    assert((chip.regs[1]&0x04)==0);
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

int main() {
  auto p=profile();
  AnalogInputManager::begin(p); wire.clear();
  // Repeated fixed input: full setup and explicit START in one transaction.
  const auto first=read(0), second=read(0);
  assert(first!=second);
  expect(0,10,{0x43,0x81,0x00,0xc0,0x00,0x08});
  expect(1,10,{0x10,0,0,0});
  expect(2,10,{0x43,0x81,0x00,0xc0,0x00,0x08}); expect(3,10,{0x10,0,0,0});
  assert(chips[0].starts==2 && chips[0].reads==2);
  assert(wire.size()==4); read(4); assert(commands(0x43)==3);
  // Every mux change restores the complete config before a fresh result.
  wire.clear();
  for (uint8_t ch: {1,2,3,0}) {
    read(ch); const auto offset=wire.size()-2;
    expect(offset,10,{0x43,static_cast<uint8_t>(0x81+(ch<<4)),0,0xc0,0,0x08});
    expect(offset+1,10,{0x10,0,0,0});
  }
  // Changed rate/configuration is applied before accepting another conversion.
  s_ads[0].config1=0xd0; wire.clear(); read(0);
  expect(0,10,{0x43,0x81,0xd0,0xc0,0,0x08});
  s_ads[0].cfg.reference=board::AdcReferenceType::ExternalRef0;
  s_ads[0].cfg.gain=2; s_ads[0].cfg.pga_bypass=false; wire.clear(); read(1);
  expect(0,10,{0x43,0x92,0xd0,0x40,0,0x08});
  // Silent ADC-only reset: SPI still succeeds, but next conversion must restore
  // mux/rate/reference before accepting data. No software invalidation signal.
  chips[0].regs.fill(0); wire.clear(); read(1);
  expect(0,10,{0x43,0x92,0xd0,0x40,0,0x08});
  assert(chips[0].regs[0]==0x92 && chips[0].regs[2]==0x40);
  // Unknown/partial WREG must not read/publish; retry always sends full setup.
  wire.clear(); failCommand=0x43; int32_t untouched=-123;
  assert(!AnalogInputManager::readCounts(2,untouched) && untouched==-123);
  assert(wire.size()==1); wire.clear(); read(2);
  expect(0,10,{0x43,0xa2,0xd0,0x40,0,0x08});
  // Failed config, RDATA or DRDY timeout never accepts an old result.
  for (int cmd: {0x43,0x10}) {
    failCommand=cmd; untouched=-123;
    assert(!AnalogInputManager::readCounts(2,untouched) && untouched==-123);
    wire.clear(); read(2); expect(0,10,{0x43,0xa2,0xd0,0x40,0,0x08});
  }
  chips[0].timeout=true; assert(!AnalogInputManager::readCounts(2,untouched));
  chips[0].timeout=false; wire.clear(); read(2);
  expect(0,10,{0x43,0xa2,0xd0,0x40,0,0x08});
  assert(adsCommand_(s_ads[0],ADS1220_CMD_RESET)); wire.clear(); read(2);
  expect(0,10,{0x43,0xa2,0xd0,0x40,0,0x08});
  // Reinitialization of both independent chips.
  AnalogInputManager::begin(p); wire.clear(); read(0); read(4);
  assert(commands(0x43)==2);

  LoggerConfig cfg; ParamStore params[2];
  cfg.sensorN=2;
  for (unsigned i=0;i<2;++i) {
    assert(params[i].set("ain",i==0?"0":"4"));
    cfg.sensors[i].type=SensorType::AnalogPot; cfg.sensors[i].params.bind(&params[i]);
  }
  assert(AnalogInputManager::configureFromConfig(cfg,500)==500);
  wire.clear(); AnalogInputManager::onLoggingStart();
  // Logging priming restores a full image even if an idle preview already ran.
  assert(commands(0x43)==2 && commands(0x08)==0 && commands(0x10)==2);
  // The public rate selector changes the actual next conversion's register one.
  assert(AnalogInputManager::configureFromConfig(cfg,100)==100);
  wire.clear();
  // Keep the synchronous call on the same hardware path while fake tasks exist.
  assert(readAdsChannelLive_(0,0,untouched));
  expect(0,10,{0x43,0x81,0x60,0xc0,0,0x08}); // 175 vs 1000 SPS normal
  assert(AnalogInputManager::configureFromConfig(cfg,500)==500);
  assert(readAdsChannelLive_(0,0,untouched));
#if ADC_TEST_ASYNC
  wire.clear();
  assert(AnalogInputManager::stoppedTimingStats()==nullptr);
  // Run real worker twice; notification/ready wait and cache publication are real.
  for (unsigned a=0;a<2;++a) {
    unsigned reads=0;
    afterRead=[&,a] { if(++reads==2) s_ads[a].asyncRun=false; };
    adcTaskFn_(reinterpret_cast<void*>(static_cast<uintptr_t>(a)));
    afterRead={};
    assert(s_ads[a].nextSeq[0]==3 && !s_ads[a].asyncRunning);
    if(a==0) assert(AnalogInputManager::stoppedTimingStats()==nullptr);
  }
  assert(AnalogInputManager::stoppedTimingStats()==&AnalogInputManager::timingStats());
  assert(commands(0x43)==4 && commands(0x08)==0 && commands(0x10)==4 && wire.size()==8);
  // A conversion may complete during the configuration transfer. Clear only
  // before that write; a late clear would discard the new notification.
  s_ads[0].asyncTask=xTaskGetCurrentTaskHandle();
  s_ads[0].drdyTask=xTaskGetCurrentTaskHandle();
  completeDuringWrite=true; const unsigned oldClears=clears;
  afterRead=[&] { assert(clears==oldClears+1 && clearCountAtWrite==oldClears+1); };
  assert(readAdsChannelLive_(0,0,untouched)); afterRead={};
  completeDuringWrite=false; s_ads[0].asyncTask=nullptr; s_ads[0].drdyTask=nullptr;
#else
  wire.clear();
  for (unsigned row=0;row<2;++row) {
    AnalogInputManager::beginSample();
    const auto transactions=wire.size();
    read(0); read(0); read(4); // columns reuse within this row only
    assert(wire.size()==transactions);
    AnalogInputManager::endSample();
  }
  assert(commands(0x43)==4 && commands(0x08)==0 && commands(0x10)==4);
#endif
  AnalogInputManager::onLoggingStop();
  wire.clear(); AnalogInputManager::onLoggingStart();
  assert(commands(0x43)==2); AnalogInputManager::onLoggingStop();
#if ADC_TEST_ASYNC
  // Task creation is deferred in this fake scheduler: both workers outlive the
  // bounded STOP wait. Publishing live 64-bit totals must remain impossible.
  assert(AnalogInputManager::stoppedTimingStats()==nullptr);
  adcTaskFn_(nullptr);
  assert(AnalogInputManager::stoppedTimingStats()==nullptr);
  adcTaskFn_(reinterpret_cast<void*>(1));
#endif
  assert(AnalogInputManager::stoppedTimingStats()==&AnalogInputManager::timingStats());
  // Synchronous multi-channel scan applies each mux independently on each chip.
  // This also exercises the fallback even in an ESP32 build with workers stopped.
  s_ads[0].channelUsed[1]=true; s_ads[0].activeChannels=2;
  wire.clear(); AnalogInputManager::beginSample();
  assert(commands(0x43)==3 && commands(0x08)==0 && commands(0x10)==3);
  assert(s_ads[0].cachedValid[0] && s_ads[0].cachedValid[1]);
  assert(s_ads[0].cachedCounts[0]!=s_ads[0].cachedCounts[1]);
  AnalogInputManager::endSample();
  // A scan timeout cannot mark a channel valid; next scan restores full setup.
  chips[0].timeout=true; AnalogInputManager::beginSample();
  assert(!s_ads[0].cachedValid[0] && !s_ads[0].cachedValid[1]);
  assert(s_ads[1].cachedValid[0]); // one failed ADC must not suppress its peer
  AnalogInputManager::endSample(); chips[0].timeout=false;
  wire.clear(); AnalogInputManager::beginSample();
  assert(commands(0x43)==3 && s_ads[0].cachedValid[0] && s_ads[0].cachedValid[1]);
  AnalogInputManager::endSample();
  assert(AnalogInputManager::timingStats().adc[0].configUs.count>0);
  assert(AnalogInputManager::timingStats().adc[0].startUs.count==0);
#if ADC_TEST_ASYNC
  failCreateAdc=1;
  AnalogInputManager::onLoggingStart();
  assert(AnalogInputManager::stoppedTimingStats()==nullptr); // ADC0 still live
  AnalogInputManager::onLoggingStop();
  adcTaskFn_(nullptr);
  assert(AnalogInputManager::stoppedTimingStats()!=nullptr); // failed ADC1 has no bit
#endif
  printf("ADC setup: %s path WREG-starts=%d, explicit START, full restore, mux/config, failures/restart PASS\n",
         ADC_TEST_ASYNC?"worker":"synchronous",ADC_TEST_WREG_STARTS);
}
