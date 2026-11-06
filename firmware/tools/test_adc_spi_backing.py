"""Check actual ADC caller object extents against the installed HAL word reads.

The driver bodies are extracted unchanged. Only the SPI boundary is replaced:
GCC tracks each caller's object through an always-inline shim and rejects
unknown extents. This checks caller backing storage, not electrical behavior.
The independent HAL guarded-page reproduction established four-byte reads.
"""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile


def function(source, name):
    match = re.search(r"bool " + name + r"\([^;{}]*\)\s*\{", source)
    assert match, name
    end, depth = match.end(), 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[match.start():end]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", required=True)
    parser.add_argument("--source", type=Path, help="Alternative ADC source for regression sensitivity")
    args = parser.parse_args()
    source = (args.source or Path(__file__).resolve().parents[1] / "src/AnalogInputManager.cpp").read_text(encoding="utf-8")
    bodies = "\n".join(function(source, name) for name in ("adsCommand_", "adsWriteRegisters_", "adsReadData_"))
    fixture = r'''
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
struct AdsDevice { bool present=true; struct {int cs_pin=47;} cfg; };
static bool s_spiReady=true;
constexpr uint8_t ADS1220_CMD_START=8,ADS1220_CMD_RDATA=16,ADS1220_CMD_WREG=64;
static unsigned commands=0,writes=0,reads=0;
static inline __attribute__((always_inline)) bool checked(const uint8_t* tx,uint8_t* rx,size_t length) {
    const size_t available=__builtin_object_size(tx,0);
    // Unknown is a test failure, never an inferred safe buffer.
    assert(available!=static_cast<size_t>(-1));
    assert(available>=((length+3U)&~size_t(3U)));
    assert((reinterpret_cast<uintptr_t>(tx)&3U)==0);
    if(length==1){assert(tx[0]==8 || tx[0]==6);++commands;}
    else if(length==5){assert(tx[0]==0x43 && tx[1]==0x81 && tx[4]==0);++writes;}
    else {assert(length==4 && tx[0]==16);assert(rx);if(rx)std::memset(rx,0,4);++reads;}
    // Exercise the same full-word source reads after proving the object bound.
    volatile uint32_t sink=0;
    for(size_t i=0;i<(length+3U)/4U;++i)sink=reinterpret_cast<const uint32_t*>(tx)[i];
    (void)sink;return true;
}
static inline __attribute__((always_inline)) bool adsTransfer_(AdsDevice&,const uint8_t* tx,uint8_t* rx,size_t length,bool=true) {
    return checked(tx,rx,length);
}
static int spiSettings_(AdsDevice&) {return 0;}
static void probeStartReleased_(void*) {}
namespace SharedSpiBus {
template<class... Tail> inline __attribute__((always_inline)) bool transfer(int,int,const uint8_t* tx,uint8_t* rx,size_t length,Tail...) {
    return checked(tx,rx,length);
}
}
// ACTUAL_ADC_CALLERS
int main(){AdsDevice dev;const uint8_t registers[4]={0x81,0xa0,0x40,0};int32_t raw;
assert(adsCommand_(dev,8));assert(adsCommand_(dev,6));
assert(adsWriteRegisters_(dev,0,registers,4));assert(adsReadData_(dev,raw));
assert(commands==2 && writes==1 && reads==1);
std::puts("actual ADC callers: known aligned backing extents cover HAL word reads; wire lengths remain 1/5/4 PASS");}
'''
    with tempfile.TemporaryDirectory(prefix="adc-spi-backing-") as temp:
        temp = Path(temp)
        cpp, exe = temp / "backing.cpp", temp / "backing.exe"
        cpp.write_text(fixture.replace("// ACTUAL_ADC_CALLERS", bodies), encoding="utf-8")
        for probe in (0, 1):
            subprocess.run([args.compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror",
                            "-Wno-unused-function", "-Wno-error=array-bounds", f"-DBODAQS_SPI_PROBE={probe}",
                            str(cpp), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
