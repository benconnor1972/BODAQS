"""Exercise actual Arduino GPIO attachment against a paused SDK publication.

Arduino code comes from the selected installed framework, not a copied driver.
The SDK boundary models ESP-IDF 4.4.7 GPIO's table-before-interrupt-handle
publication and blocking interrupt allocation. No electrical timing is simulated.
See https://github.com/espressif/esp-idf/blob/v4.4.7/components/driver/gpio.c.
"""
from pathlib import Path


def function(source, declaration):
    start = source.index(declaration)
    opening = source.index("{", start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


def fixture_with_gpio_startup(fixture, framework):
    source = (Path(framework) / "cores/esp32/esp32-hal-gpio.c").read_text(encoding="utf-8")
    types = source[source.index("typedef void (*voidFuncPtr)"):source.index('#include "driver/rtc_io.h"', source.index("typedef void (*voidFuncPtr)"))]
    functions = "\n".join(function(source, declaration) for declaration in (
        "static void ARDUINO_ISR_ATTR __onPinInterrupt",
        "extern void __attachInterruptFunctionalArg",
        "extern void __attachInterruptArg"))
    adapter = r'''
// GPIO allocation may yield while its table is visible but its ISR handle is not.
static std::atomic<bool> sdkTablePublished=false,sdkHandleReady=false;
static std::atomic<bool> registrationWaiter=false;
static bool releaseInstallation=false;
static std::mutex installMutex;
static std::condition_variable installCv;
using esp_err_t=int;
static constexpr int ESP_OK=0,ESP_ERR_INVALID_STATE=0x103;
#define SOC_GPIO_PIN_COUNT 49
#define ARDUINO_ISR_FLAG 0
#define log_e(...) ((void)0)
using gpio_num_t=int;
using gpio_int_type_t=int;
struct gpio_hal_context_t {void* dev;};
#define GPIO_PORT_0 0
#define GPIO_LL_GET_HW(port) nullptr
static void gpio_hal_input_enable(gpio_hal_context_t*,uint8_t) {}
static void gpio_set_intr_type(gpio_num_t,gpio_int_type_t) {}
static void gpio_wakeup_enable(gpio_num_t,gpio_int_type_t) {}
static esp_err_t gpio_install_isr_service(int) {
  if(sdkTablePublished.exchange(true))return ESP_ERR_INVALID_STATE;
  std::unique_lock<std::mutex> lock(installMutex);
  installCv.notify_all();installCv.wait(lock,[]{return releaseInstallation;});
  sdkHandleReady=true;return ESP_OK;
}
static void gpio_isr_handler_add(gpio_num_t pin,void (*fn)(void*),void* arg) {
  if(!sdkHandleReady) {
    fputs("REPRODUCED: gpio_isr_handler_add reaches esp_intr_get_cpu with NULL ISR handle\n",stderr);
    abort();
  }
  std::lock_guard<std::mutex> lock(gpioMutex);gpio[pin].isr=fn;gpio[pin].arg=arg;
}
void cleanupFunctional(void*) {}
'''
    old = function(fixture, "void attachInterruptArg(")
    fixture = fixture.replace(old, adapter + types + functions + r'''
void attachInterruptArg(uint8_t pin,void (*fn)(void*),void* arg,int mode) {
  __attachInterruptArg(pin,fn,arg,mode);
}
''')
    fixture = fixture.replace("BaseType_t xSemaphoreTake(SemaphoreHandle_t m,TickType_t timeout) {", r'''
BaseType_t xSemaphoreTake(SemaphoreHandle_t m,TickType_t timeout) {
  if(m!=sharedSpiLock) {
    assert(timeout==100); // Keep the production registration deadline unchanged.
    if(m->try_lock()) {
      // Force the second worker to attempt this real mutex before the first
      // owner publishes the SDK table. The old flag missed this ordering.
      if(!sdkTablePublished)while(!registrationWaiter)std::this_thread::yield();
      return pdTRUE;
    }
    registrationWaiter=true;
    return m->try_lock_for(std::chrono::milliseconds(timeout));
  }
''')
    fixture = fixture[:fixture.index("int main() {")] + r'''
static bool workersRunning() {
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
  return AnalogInputManager::probeWorkersRunning();
#else
  const auto& stats=AnalogInputManager::timingStats();
  return stats.adc[0].asyncRunning && stats.adc[1].asyncRunning;
#endif
}
static bool workersStopped() {
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
  return AnalogInputManager::probeWorkersStopped();
#else
  const auto& stats=AnalogInputManager::timingStats();
  return !stats.adc[0].asyncRunning && !stats.adc[1].asyncRunning;
#endif
}
template<class F> static void awaitGpio(const char* observation,F pred) {
  const auto until=millis()+1000;
  while(!pred() && millis()<until)delay(1);
  if(!pred()){fprintf(stderr,"GPIO await failed: %s\n",observation);abort();}
}
int main() {
  auto board=adcBoard();AnalogInputManager::begin(board);
  LoggerConfig cfg;cfg.sensorN=2;cfg.sampleRateHz=500;
  for(auto& s:cfg.sensors){s.type=SensorType::AnalogPot;s.mutedDefault=false;}
  char ain0[]="sensor0.ain=0",ain4[]="sensor1.ain=4";
  assert(ConfigManager::parseLine(ain0,cfg));assert(ConfigManager::parseLine(ain4,cfg));
  assert(AnalogInputManager::configureFromConfig(cfg,500)==500);
  AnalogInputManager::onLoggingStart();
  // Both real workers start; the first is paused in actual Arduino attachment.
  awaitGpio("SDK table publication",[]{return sdkTablePublished.load();});
  awaitGpio("actual registration mutex contention",[]{return registrationWaiter.load();});
  assert(!sdkHandleReady);
  {std::lock_guard<std::mutex> lock(installMutex);releaseInstallation=true;}
  installCv.notify_all();
  awaitGpio("workers running",[]{return workersRunning();});
  awaitGpio("first START on both ADCs",[]{return starts[0]>=1 && starts[1]>=1;});
  complete(0);complete(1);
  awaitGpio("DRDY read on both ADCs",[]{return reads[0]>=2 && reads[1]>=2;});
  stopAdc_();joinTasks();assert(workersStopped());
  assert(sdkHandleReady);
  // The same service survives STOP/restart; no concurrent reinstallation needed.
  AnalogInputManager::onLoggingStart();
  awaitGpio("workers running",[]{return workersRunning();});
  stopAdc_();joinTasks();assert(workersStopped());
  puts("Actual Arduino GPIO wrapper: paused first allocation, two ADC workers, DRDY, STOP/restart passed");
}
'''
    return fixture
