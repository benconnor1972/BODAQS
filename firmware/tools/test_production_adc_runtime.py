"""Run the real ADC manager/owner against an independent SPI/DRDY/timer model."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = (root / "src/AnalogInputManager.cpp").read_text(encoding="utf-8")
    source = re.sub(r"^#include[^\n]*\n", "", source, flags=re.MULTILINE)
    # Reuse the independently specified chip model; extend its decoder for the
    # read-registers + read-data + next-MUX/START transaction used by production.
    model = (root / "test/adc_setup_runtime_fixture.cpp").read_text(encoding="utf-8").split("int main()", 1)[0]
    model = model.replace("uint32_t micros() { nowUs += 10; return nowUs; }", "uint32_t micros() { nowUs += 1; return nowUs; }")
    model = model.replace("int analogRead(uint8_t) { return 123; }", "int analogRead(uint8_t) { return 123; }\nunsigned resolution=0; void analogReadResolution(unsigned bits) { resolution=bits; }")
    model = re.sub(r"uint32_t ulTaskNotifyTake\(int, TickType_t ticks\) \{.*?\n\}",
                   "uint32_t ulTaskNotifyTake(int, TickType_t ticks);", model, flags=re.S)
    model = model.replace("// PRODUCTION_MANAGER", "int8_t digitalPinToAnalogChannel(uint8_t pin) {return pin >= 1 && pin <= 20 ? int8_t(pin-1) : -1;}\n// PRODUCTION_MANAGER")
    timers = r'''
constexpr uint32_t portMAX_DELAY=UINT32_MAX;
constexpr int ESP_OK=0, MALLOC_CAP_INTERNAL=1, MALLOC_CAP_8BIT=2, MALLOC_CAP_DMA=4;
unsigned heap_caps_get_free_size(unsigned) { return 65536; }
unsigned heap_caps_get_largest_free_block(unsigned) { return 32768; }
unsigned uxTaskGetStackHighWaterMark(void*) { return 2048; }
struct Parked {};
struct FakeTimer {void (*callback)(void*)=nullptr; void* arg=nullptr; uint64_t deadline=0; bool armed=false;} timer;
using esp_timer_handle_t=FakeTimer*;
struct esp_timer_create_args_t {void (*callback)(void*)=nullptr; void* arg=nullptr; const char* name=nullptr;};
unsigned notifications=0, earlyWakeCount=0, lateWake=0;
bool earlyHints=false, failArm=false, corruptReadback=false, negativeConversions=false;
int32_t delivered[2][4]={};
void xTaskNotifyGive(void*) { ++notifications; }
int esp_timer_create(const esp_timer_create_args_t* args, esp_timer_handle_t* out) {
  timer.callback=args->callback; timer.arg=args->arg; *out=&timer; return ESP_OK;
}
int esp_timer_stop(esp_timer_handle_t) { timer.armed=false; return ESP_OK; }
int esp_timer_start_once(esp_timer_handle_t, uint64_t duration) {
  if(failArm)return 1;
  timer.deadline=nowUs+duration; timer.armed=true; return ESP_OK;
}
uint32_t ulTaskNotifyTake(int, TickType_t ticks) {
  if (!ticks) { ++clears; const auto count=notifications;notifications=0;return count; }
  if (notifications) {const auto count=notifications;notifications=0;return count;}
  if (timer.armed) {
    if(earlyHints && nowUs+100<timer.deadline) {nowUs+=100;++earlyWakeCount;return 1;}
    nowUs=timer.deadline+lateWake;lateWake=0;timer.armed=false;
    timer.callback(timer.arg);notifications=0;return 1;
  }
  if (ticks==portMAX_DELAY)throw Parked{};
  nowUs+=ticks*1000;return 0;
}
'''
    model = model.replace("// PRODUCTION_MANAGER", timers + "\n" + source)
    model = model.replace("  } else if (cmd==0x10) {", r'''
  } else if (cmd==0x23) {
    assert(chip.active && !chip.timeout && nowUs>=chip.readyAt);
    memcpy(rx+1,chip.regs.data(),4);
    const unsigned channel=(chip.regs[0]>>4)-8;
    assert(channel<4);
    const int32_t magnitude=(channel+1)*100000+chip.generation*1000;
    const int32_t value=negativeConversions ? -magnitude : magnitude;
    rx[6]=value>>16;rx[7]=value>>8;rx[8]=value;
    delivered[cs-10][channel]=value;++chip.reads;chip.active=false;
    if(corruptReadback){rx[1]^=0x10;corruptReadback=false;}
    if(len==12) {
      assert(tx[9]==0x40 && tx[11]==0x08);
      chip.regs[0]=tx[10];++chip.starts;++chip.generation;
      chip.active=true;chip.readyAt=nowUs+40;
    }else assert(len==9);
  } else if (cmd==0x02) { chip.active=false;
  } else if (cmd==0x10) {''')
    fixture = (root / "test/production_adc_runtime_fixture.cpp").read_text(encoding="utf-8").replace("// BASE_ADC_MODEL", model)
    with tempfile.TemporaryDirectory(prefix="bodaqs-production-adc-") as tmp:
        folder = Path(tmp)
        (folder / "SPI.h").write_text("#pragma once\n#include <stdint.h>\nconstexpr int MSBFIRST=1,SPI_MODE1=1;\nstruct SPISettings {SPISettings(uint32_t,int,int){}};\n", encoding="utf-8")
        cpp, exe = folder / "adc.cpp", folder / "adc.exe"
        cpp.write_text(fixture, encoding="utf-8")
        flags = {"ADC_TEST_ASYNC": 1, "ADC_TEST_WREG_STARTS": 0, "ADC_TEST_EXPECTED_PRIORITY": 4,
                 "BODAQS_PRODUCTION_RECORDING": 1, "BODAQS_ADC_CONCENTRATED_SCAN_BENCH": 1,
                 "BODAQS_ADC_BOUNDARY_BENCH": 1, "BODAQS_ADC_DUAL_SCAN_BENCH": 1,
                 "BODAQS_ADC_ROW_HANDOFF": 1, "BODAQS_ADC_COMBINED_CAPTURE": 1,
                 "BODAQS_ADC_INLINE_ROW": 1, "BODAQS_ADC_SCAN_PIPELINE": 1,
                 "BODAQS_ADC_SCAN_MUX_ONLY": 1, "BODAQS_ADC_CONTINUOUS_LATEST": 1,
                 "BODAQS_ADC_RAW_RECORDING_BENCH": 1, "BODAQS_ADC_TASK_PRIORITY": 4,
                 "BODAQS_ADC_SCAN_ROW_PHASE": 0}
        subprocess.run([args.compiler, "-std=c++17", "-Wall", "-Wextra", "-Wno-unused-variable", "-Wno-unused-function", "-Wno-unused-parameter",
                        *(f"-D{key}={value}" for key, value in flags.items()),
                        "-I", str(folder), "-I", str(root / "test/stubs"), "-I", str(root / "src"),
                        str(cpp), str(root / "src/SensorParams.cpp"), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True, timeout=20)


if __name__ == "__main__":
    main()
