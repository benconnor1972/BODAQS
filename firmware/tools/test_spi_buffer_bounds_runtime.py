"""Check real ADC call-site buffer extents against ESP32 HAL word reads.

Only peripheral registers and pointer bounds are instrumented. The production
ADC helpers and installed spiTransferBytesNL loop are compiled into the fixture.
This is a memory-contract regression, not a physical SPI-fault reproduction.
"""
import argparse
from pathlib import Path
import subprocess
import tempfile
from runtime_test_helpers import definition


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler',default='g++')
    parser.add_argument('--manager-source',type=Path)
    parser.add_argument('--skip-command',action='store_true',help='Exercise combined setup independently for negative proof')
    parser.add_argument('--hal-source',type=Path,default=Path.home()/'.platformio/packages/framework-arduinoespressif32/cores/esp32/esp32-hal-spi.c')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    manager=(args.manager_source or root/'src/AnalogInputManager.cpp').read_text(encoding='utf-8')
    helpers='\n'.join(definition(manager,marker) for marker in (
        'bool adsCommand_(', 'bool adsWriteRegistersAndStart_(', 'bool adsReadData_('))
    driver=definition(args.hal_source.read_text(encoding='utf-8'),'void spiTransferBytesNL(')
    original='uint32_t * data = (uint32_t*)data_in;'
    assert driver.count(original)==1,'Installed HAL source changed; re-audit read instrumentation'
    driver=driver.replace(original,'CheckedWords data(data_in);')
    fixture=r'''
#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cstdio>
#include <type_traits>
static const void* sourceBase;
static size_t sourceBytes,wordReads,lastWireBytes;
struct CheckedWords {
 const uint8_t* p;
 explicit CheckedWords(const void* base):p(static_cast<const uint8_t*>(base)) {}
 explicit operator bool() const {return p!=nullptr;}
 uint32_t operator[](size_t i) const {
   const auto offset=size_t(p-static_cast<const uint8_t*>(sourceBase))+4*i;
   assert(offset+sizeof(uint32_t)<=sourceBytes && "ESP32 HAL reads beyond ADC TX object");
   uint32_t result;std::memcpy(&result,p+4*i,4);++wordReads;return result;
 }
 CheckedWords& operator+=(size_t n) {p+=4*n;return *this;}
};
// Hardware auto-clears USR/UPDATE; no physical transfer is modelled.
struct AutoClear {AutoClear& operator=(int) {return *this;} explicit operator bool() const {return false;}};
struct Registers {
 struct {uint32_t usr_mosi_dbitlen=0;} mosi_dlen;
 struct {uint32_t usr_miso_dbitlen=0;} miso_dlen;
 struct {AutoClear usr,update;} cmd;
 uint32_t data_buf[16]={};
};
struct spi_t {Registers* dev;};
// PRODUCTION_DRIVER
struct AdsDevice {bool present=true;struct {int cs_pin=47;} cfg;};
static bool s_spiReady=true;
constexpr uint8_t ADS1220_CMD_WREG=0x40,ADS1220_CMD_START=0x08,ADS1220_CMD_RDATA=0x10;
template<typename Tx,typename Rx>
bool adsTransfer_(AdsDevice&,Tx&& tx,Rx&& rx,size_t length) {
 using T=typename std::remove_reference<Tx>::type;
 static_assert(std::is_array<T>::value || std::is_pointer<T>::value,"unexpected source type");
 sourceBase=tx;
 // Array references retain the actual object extent at the ADC caller. The
 // old &cmd expression points to exactly one byte, not a full source word.
 if constexpr(std::is_array<T>::value) sourceBytes=sizeof(T);
 else sourceBytes=sizeof(typename std::remove_pointer<T>::type);
 uint8_t* output=nullptr;
 if constexpr(!std::is_same<typename std::decay<Rx>::type,std::nullptr_t>::value) {
   output=rx;assert(reinterpret_cast<uintptr_t>(output)%alignof(uint32_t)==0);
 }
 Registers registers;spi_t spi{&registers};
 spiTransferBytesNL(&spi,tx,output,uint32_t(length));
 assert(reinterpret_cast<uintptr_t>(tx)%alignof(uint32_t)==0 && "ESP32 HAL requires word alignment");
 lastWireBytes=length;
 assert(registers.mosi_dlen.usr_mosi_dbitlen+1==length*8); // Padding never clocks extra bytes.
 return true;
}
// PRODUCTION_ADC_HELPERS
int main(int argc,char**) {
 AdsDevice adc;
 const uint8_t registers[4]={0x81,0x20,0x40,0};int32_t raw=0;
 if(argc==1) {assert(adsCommand_(adc,0x06));assert(lastWireBytes==1);}
 assert(adsWriteRegistersAndStart_(adc,0,registers,4));assert(lastWireBytes==6);
 assert(adsReadData_(adc,raw));assert(lastWireBytes==4);
 assert(wordReads>0);
 puts("Actual ESP32 HAL / production ADC buffer bounds, word alignment and unchanged wire lengths PASS");
}
'''.replace('// PRODUCTION_DRIVER',driver).replace('// PRODUCTION_ADC_HELPERS',helpers)
    with tempfile.TemporaryDirectory(prefix='bodaqs-spi-bounds-') as directory:
        cpp=Path(directory)/'bounds.cpp';exe=Path(directory)/'bounds.exe'
        cpp.write_text(fixture,encoding='utf-8')
        subprocess.run([args.compiler,'-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(exe)],check=True)
        subprocess.run([str(exe),*(['skip-command'] if args.skip_command else [])],check=True)


if __name__=='__main__':
    main()
