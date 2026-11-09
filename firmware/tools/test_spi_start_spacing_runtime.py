"""Exercise production SPI CS timing with a deterministic hardware/RTOS clock."""
import argparse
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="bodaqs-spi-spacing-") as temp:
        temp = Path(temp)
        (temp / "freertos").mkdir()
        (temp / "Arduino.h").write_text('''#pragma once
#include <stdint.h>
#include <stddef.h>
extern uint32_t nowUs, lockWaitUs, setupUs, wireUs;
extern bool lockOk;
uint32_t micros();
void delayMicroseconds(uint32_t);
void digitalWrite(uint8_t, int);
constexpr int LOW=0, HIGH=1;
''')
        (temp / "SPI.h").write_text('''#pragma once
#include "Arduino.h"
struct SPISettings {};
struct SPIClass {
 void begin(int,int,int) {}
 void beginTransaction(const SPISettings&) {nowUs+=setupUs;}
 void transferBytes(const uint8_t*,uint8_t*,size_t) {nowUs+=wireUs;}
 void endTransaction() {}
};
extern SPIClass SPI;
''')
        (temp / "freertos/FreeRTOS.h").write_text('''#pragma once
#define pdMS_TO_TICKS(ms) (ms)
#define pdTRUE 1
''')
        (temp / "freertos/semphr.h").write_text('''#pragma once
#include "Arduino.h"
using SemaphoreHandle_t=void*;
inline SemaphoreHandle_t xSemaphoreCreateMutex() {return reinterpret_cast<void*>(1);}
inline int xSemaphoreTake(SemaphoreHandle_t,uint32_t) {nowUs+=lockWaitUs;return lockOk;}
inline void xSemaphoreGive(SemaphoreHandle_t) {}
''')
        cpp = temp / "fixture.cpp"
        cpp.write_text('''#include "SharedSpiBus.h"
#include <cassert>
#include <cstdio>
#include <vector>
uint32_t nowUs=100,lockWaitUs=0,setupUs=0,wireUs=128;
bool lockOk=true;
SPIClass SPI;
static std::vector<uint32_t> starts;
uint32_t micros() {return nowUs;}
void delayMicroseconds(uint32_t us) {nowUs+=us;}
void digitalWrite(uint8_t,int state) {if(state==LOW) starts.push_back(nowUs);}
int main() {
 board::SPIProfile profile={};profile.present=true;profile.sck=1;profile.miso=2;profile.mosi=3;
 assert(SharedSpiBus::begin(profile));
 SPISettings settings;uint8_t tx[256]={},rx[256]={};
 auto transfer=[&](uint32_t pace) {return SharedSpiBus::transfer(4,settings,tx,rx,256,10,pace);};
 assert(transfer(500));assert(starts.back()==100); // no artificial first-slot delay
 assert(transfer(500));assert(starts.back()==600);
 lockWaitUs=700;setupUs=50;
 assert(transfer(500));assert(starts.back()==1478); // lock/setup delay already satisfies spacing
 lockWaitUs=0;setupUs=0;
 assert(transfer(500));assert(starts.back()==1978); // last actual CS, not pre-lock call time
 wireUs=800;assert(transfer(500));assert(starts.back()==2478);
 assert(transfer(500));assert(starts.back()==3278); // no added delay after a slow transfer
 wireUs=128;assert(transfer(0));assert(starts.back()==4078); // normal caller remains unpaced
 assert(transfer(500));assert(starts.back()==4578); // preceding shared-bus transaction also respected
 const auto count=starts.size();lockOk=false;assert(!transfer(500));assert(starts.size()==count);
 lockOk=true;assert(transfer(500));assert(starts.back()==5078);
 nowUs=0xffffff00u;assert(transfer(500));assert(starts.back()==0xffffff00u);
 assert(transfer(500));assert(starts.back()==244); // unsigned micros wrap
 assert(transfer(0));assert(starts.back()==372);
 assert(SharedSpiBus::diagnostics().transactions==starts.size());
 puts("production SPI spacing: first, short/slow, contention, unpaced, failure and wrap PASS");
}
''')
        exe = temp / "fixture.exe"
        subprocess.run([args.compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                        "-DESP32", "-I", str(temp), "-I", str(root / "src"),
                        str(cpp), str(root / "src/SharedSpiBus.cpp"), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
