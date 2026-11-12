"""Exercise production SPI CS timing with a deterministic hardware/RTOS clock."""
import argparse
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    parser.add_argument("--bus-source", type=Path, help="Saved SharedSpiBus.cpp for regression checks")
    parser.add_argument("--cs-setup", action="store_true", help="Check CS-to-clock setup and ordinary caller isolation")
    parser.add_argument("--without-setup-delay",action="store_true",help="Negative proof: remove only the production setup wait")
    parser.add_argument("--capture-disabled",action="store_true")
    parser.add_argument("--boundary-trace",action="store_true")
    parser.add_argument("--pipeline-trace",action="store_true")
    parser.add_argument("--phase-timing",action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="bodaqs-spi-spacing-") as temp:
        temp = Path(temp)
        (temp / "freertos").mkdir()
        (temp / "Arduino.h").write_text('''#pragma once
#include <stdint.h>
#include <stddef.h>
extern uint32_t nowUs, lockWaitUs, setupUs, wireUs;
extern uint32_t finishUs;
extern bool lockOk;
extern bool lockHeld, transactionActive;
extern bool selected, requireSlaveSetup;
extern uint32_t selectedAtUs,firstClockUs;
extern size_t lastWireLength;
extern uint8_t lastWireCommand;
uint32_t micros();
void delayMicroseconds(uint32_t);
void digitalWrite(uint8_t, int);
constexpr int LOW=0, HIGH=1;
''')
        (temp / "SPI.h").write_text('''#pragma once
#include "Arduino.h"
#include <cassert>
struct SPISettings {};
struct SPIClass {
 void begin(int,int,int) {}
 void beginTransaction(const SPISettings&) {assert(lockHeld && !transactionActive);transactionActive=true;nowUs+=setupUs;}
 void transferBytes(const uint8_t* tx,uint8_t* rx,size_t length) {
   assert(lockHeld && transactionActive && selected);firstClockUs=nowUs;
   lastWireLength=length;lastWireCommand=tx?tx[0]:0;
   if(requireSlaveSetup && rx) rx[0]=uint32_t(nowUs-selectedAtUs)>=5?0x42:0;
   nowUs+=wireUs;
 }
 void endTransaction() {assert(transactionActive);transactionActive=false;nowUs+=finishUs;}
};
extern SPIClass SPI;
''')
        (temp / "freertos/FreeRTOS.h").write_text('''#pragma once
#define pdMS_TO_TICKS(ms) (ms)
#define pdTRUE 1
''')
        (temp / "freertos/semphr.h").write_text('''#pragma once
#include "Arduino.h"
#include <cassert>
using SemaphoreHandle_t=void*;
inline SemaphoreHandle_t xSemaphoreCreateMutex() {return reinterpret_cast<void*>(1);}
inline int xSemaphoreTake(SemaphoreHandle_t,uint32_t) {assert(!lockHeld);nowUs+=lockWaitUs;lockHeld=lockOk;return lockOk;}
inline void xSemaphoreGive(SemaphoreHandle_t) {assert(lockHeld && !transactionActive);lockHeld=false;}
''')
        cpp = temp / "fixture.cpp"
        cpp.write_text('''#include "SharedSpiBus.h"
#include <cassert>
#include <cstdio>
#include <vector>
#include <functional>
uint32_t nowUs=100,lockWaitUs=0,setupUs=0,wireUs=128;
uint32_t finishUs=0;
bool lockOk=true;
bool lockHeld=false,transactionActive=false;
bool selected=false,requireSlaveSetup=false;
uint32_t selectedAtUs=0,firstClockUs=0;
size_t lastWireLength=0;uint8_t lastWireCommand=0;
static std::function<void()> duringWait;
SPIClass SPI;
static std::vector<uint32_t> starts;
uint32_t micros() {return nowUs;}
void delayMicroseconds(uint32_t us) {
 if(selected) assert(lockHeld && transactionActive);
 const auto began=nowUs;
 if(duringWait) {auto callback=std::move(duringWait);duringWait={};callback();}
 const auto elapsed=nowUs-began;if(elapsed<us) nowUs+=us-elapsed;
}
void digitalWrite(uint8_t,int state) {
 assert(lockHeld && transactionActive);
 if(state==LOW) {assert(!selected);selected=true;selectedAtUs=nowUs;starts.push_back(nowUs);}
 else {assert(selected);selected=false;}
}
int main() {
 board::SPIProfile profile={};profile.present=true;profile.sck=1;profile.miso=2;profile.mosi=3;
 assert(SharedSpiBus::begin(profile));
 SPISettings settings;uint8_t tx[256]={},rx[256]={};
 auto transfer=[&](uint32_t pace) {return SharedSpiBus::transfer(4,settings,tx,rx,256,10,pace);};
 SpiTransactionContext first;
 assert(SharedSpiBus::transfer(4,settings,tx,rx,256,10,500,0,&first));assert(starts.back()==100);
#if (defined(BODAQS_MEASUREMENT_REPLY_CAPTURE) && BODAQS_MEASUREMENT_REPLY_CAPTURE) || (defined(BODAQS_PIPELINE_TRACE) && BODAQS_PIPELINE_TRACE)
 assert(first.valid && !first.previousValid && first.previousCs==-1 && first.sequence==1);
#else
 assert(!first.valid);
#endif
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
 // A different device must not reset the master's deadline. ADC work must
 // complete while the paced caller owns neither mutex nor SPI transaction.
 nowUs=10000;assert(transfer(500));assert(starts.back()==10000);
 duringWait=[&] {
   assert(!lockHeld && !transactionActive);
   assert(SharedSpiBus::transfer(5,settings,tx,rx,6));
   assert(starts.back()==10128);
 };
 assert(transfer(500));assert(starts.back()==10500);
 // Rechecking after reacquiring the mutex protects a same-CS caller that
 // used the gap. Even its unpaced transfer establishes a new own-CS origin.
 duringWait=[&] {assert(!lockHeld);assert(transfer(0));assert(starts.back()==10628);};
 assert(transfer(500));assert(starts.back()==11128);
 assert(!lockHeld && !transactionActive);
 assert(SharedSpiBus::diagnostics().transactions==starts.size());
 // The exact context is copied while locked, including intervening ADC traffic.
 SpiTransactionContext observed;
 nowUs=30000;tx[0]=0x12;
 assert(SharedSpiBus::transfer(5,settings,tx,rx,6));
 tx[0]=0x42;
 assert(SharedSpiBus::transfer(4,settings,tx,rx,256,10,0,0,&observed));
 assert(lastWireLength==256 && lastWireCommand==0x42 && tx[0]==0x42);
#if (defined(BODAQS_MEASUREMENT_REPLY_CAPTURE) && BODAQS_MEASUREMENT_REPLY_CAPTURE) || (defined(BODAQS_PIPELINE_TRACE) && BODAQS_PIPELINE_TRACE)
 assert(observed.valid && observed.previousValid && observed.previousCs==5 && observed.cs==4);
 assert(observed.previousReleaseUs==30128 && observed.selectedUs==30128 && observed.releasedUs==30256);
 assert(observed.commandValid && observed.command==0x42 && observed.bytes==256);
 assert(observed.previousCommandValid && observed.previousCommand==0x12 && observed.previousBytes==6);
 const auto saved=observed;
 assert(SharedSpiBus::transfer(5,settings,tx,rx,6));
 assert(observed.sequence==saved.sequence && observed.previousCs==5);
#else
 assert(!observed.valid);
#endif
 lockOk=false;assert(!SharedSpiBus::transfer(4,settings,tx,rx,256,10,0,0,&observed));
 assert(!observed.valid);lockOk=true;
 // CS_SETUP_CHECK
 puts("production SPI spacing: unlocked ADC interleave, per-CS deadline, concurrent same-CS recheck, failure and wrap PASS");
}
''')
        if args.phase_timing:
            cpp.write_text(cpp.read_text().replace('// CS_SETUP_CHECK','''
 nowUs=40000;lockWaitUs=17;setupUs=11;wireUs=48;finishUs=7;
 SpiTransferTiming phases;
 assert(SharedSpiBus::transfer(5,settings,tx,rx,6,10,0,0,nullptr,&phases));
 assert(phases.lockWaitUs==17 && phases.prepareUs==11 && phases.transferUs==48 && phases.finishUs==7);
 nowUs=UINT32_MAX-30;
 assert(SharedSpiBus::transfer(5,settings,tx,rx,6,10,0,0,nullptr,&phases));
 assert(phases.lockWaitUs==17 && phases.prepareUs==11 && phases.transferUs==48 && phases.finishUs==7);
 lockOk=false;
 assert(!SharedSpiBus::transfer(5,settings,tx,rx,6,10,0,0,nullptr,&phases));
 assert(phases.lockWaitUs==17 && !phases.prepareUs && !phases.transferUs && !phases.finishUs);
 assert(!SharedSpiBus::transfer(5,settings,tx,rx,0,10,0,0,nullptr,&phases));
 assert(!phases.lockWaitUs && !phases.prepareUs && !phases.transferUs && !phases.finishUs);
 lockOk=true;lockWaitUs=setupUs=finishUs=0;wireUs=128;
 puts("actual bus phase timing: independent wait/setup/transfer/finish, clock wrap and failed-call clearing PASS");
 // CS_SETUP_CHECK
'''))
        if args.cs_setup:
            cpp.write_text(cpp.read_text().replace('// CS_SETUP_CHECK','''
 requireSlaveSetup=true;nowUs=20000;wireUs=128;
 auto setupTransfer=[&] {return SharedSpiBus::transfer(4,settings,tx,rx,256,10,500,5);};
 assert(setupTransfer());assert(starts.back()==20000);
 assert(firstClockUs-selectedAtUs>=5 && rx[0]==0x42);
 assert(setupTransfer());assert(starts.back()==20500); // setup does not replace own-CS spacing
 assert(firstClockUs==20505);
 duringWait=[&] {
   assert(!lockHeld && !transactionActive);
   assert(SharedSpiBus::transfer(5,settings,tx,rx,6));
   assert(firstClockUs==selectedAtUs); // ADC/default call adds no setup wait
 };
 assert(setupTransfer());assert(starts.back()==21000 && firstClockUs==21005);
 nowUs=0xfffffffdu;assert(setupTransfer());
 assert(uint32_t(firstClockUs-selectedAtUs)==5 && firstClockUs==2 && rx[0]==0x42);
 const auto n=starts.size();lockOk=false;assert(!setupTransfer());assert(starts.size()==n);
 lockOk=true;
 assert(SharedSpiBus::transfer(5,settings,tx,rx,6));
 assert(firstClockUs==selectedAtUs && rx[0]==0); // model alone is not a physical diagnosis
 assert(!selected && !lockHeld && !transactionActive);
 puts("production CS setup: slave first-byte readiness, locked/selected setup, ADC isolation, pacing and wrap PASS");
 // CS_SETUP_CHECK
'''))
        bus=args.bus_source or root / 'src/SharedSpiBus.cpp'
        if args.boundary_trace or args.pipeline_trace:
            assert args.pipeline_trace or not args.capture_disabled
            cpp.write_text(cpp.read_text().replace(' // CS_SETUP_CHECK','''
 SpiTransactionContext before,after;
 assert(SharedSpiBus::transfer(4,settings,tx,rx,256,10,0,0,&before));
 assert(before.deviceSequenceValid && before.deviceSequence>1);
 assert(SharedSpiBus::transfer(5,settings,tx,rx,6));
 assert(SharedSpiBus::transfer(4,settings,tx,rx,256,10,0,0,&after));
 assert(after.deviceSequence==before.deviceSequence+1); // ADC has its own counter
 before=after;
 assert(SharedSpiBus::transfer(4,settings,tx,rx,84)); // no context requested
 assert(SharedSpiBus::transfer(4,settings,tx,rx,256,10,0,0,&after));
 assert(after.deviceSequence==before.deviceSequence+2);
 SharedSpiBus::testSeedSequence(4,UINT32_MAX-1);
 assert(SharedSpiBus::transfer(4,settings,tx,rx,256,10,0,0,&after));
 assert(!after.deviceSequenceValid && after.deviceSequence==UINT32_MAX);
 assert(SharedSpiBus::transfer(4,settings,tx,rx,256,10,0,0,&after));
 assert(!after.deviceSequenceValid && after.deviceSequence==UINT32_MAX);
 puts("actual bus: per-CS identity, foreign same-CS callers, saturation PASS");
 // CS_SETUP_CHECK
''').replace('int main() {','namespace SharedSpiBus {void testSeedSequence(unsigned,uint32_t);}\nint main() {'))
            # Test-only seed in the real translation unit reaches the otherwise
            # private counter; production has no reset/setter interface.
            injected=bus.read_text()+ '\nnamespace SharedSpiBus {void testSeedSequence(unsigned cs,uint32_t n) {s_deviceSequence[cs]=n;}}\n'
            bus=temp/'trace-bus.cpp';bus.write_text(injected)
        if args.without_setup_delay:
            assert args.cs_setup
            text=bus.read_text();line='  if(csSetupUs) delayMicroseconds(csSetupUs);'
            assert text.count(line)==1
            changed=text.replace(line,'  (void)csSetupUs; // negative timing proof')
            assert changed!=text and line not in changed
            bus=temp/'without-setup.cpp';bus.write_text(changed)
        exe = temp / "fixture.exe"
        subprocess.run([args.compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                        "-DESP32", f"-DBODAQS_MEASUREMENT_REPLY_CAPTURE={int(not args.capture_disabled)}", f"-DBODAQS_SPI_BOUNDARY_TRACE={int(args.boundary_trace)}", f"-DBODAQS_PIPELINE_TRACE={int(args.pipeline_trace)}", "-I", str(temp), "-I", str(root / "src"),
                        str(cpp), str(bus), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
