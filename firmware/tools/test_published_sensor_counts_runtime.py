"""Actual preview adapter functions with independent hardware/publication models."""
import argparse
from pathlib import Path
import subprocess
import tempfile

from runtime_test_helpers import definition


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', default='g++')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    source=(root/'src/AnalogPotSensor.cpp').read_text(encoding='utf-8')
    fixture=r'''
#include "PublishedSensorCounts.h"
#include <cassert>
#include <cstring>
#include <cmath>
enum class OutputMode {RAW,LINEAR,POLY,LUT};
struct LocalAdcSnapshot {};
static unsigned reads=0, now=100;
static int hardware=42; static bool hardwareValid=true;
uint32_t millis() {return now;}
uint32_t micros() {return now*1000;}
void copyField_(char* dst,size_t cap,const char* text) {if(cap){std::strncpy(dst,text,cap-1);dst[cap-1]=0;}}
class AnalogPotSensor {
public:
  PublishedSensorCounts m_publishedCounts;
  uint32_t m_nextIdleSampleMs=0;
  bool m_recordRaw=false,m_muted=false,m_invert=false;
  double counts_per_mm_=2; int installed_zero_count_=10;
  char m_outputUnitsLabel[8]="mm";
  void loop(); void publishAcquiredCounts(int32_t,uint32_t,uint16_t);
  bool hasRawCounts() const; int32_t currentRawCounts() const;
  bool readPreviewValue(OutputMode,float&,char*,size_t);
  int readOnce(const LocalAdcSnapshot* =nullptr,bool* valid=nullptr) const {
    ++reads;if(valid)*valid=hardwareValid;return hardware;
  }
};
// ACTUAL_ADAPTER
int main() {
  AnalogPotSensor sensor; char unit[16];float value=0;
  assert(!sensor.hasRawCounts());
  assert(!sensor.readPreviewValue(OutputMode::RAW,value,unit,sizeof unit));
  assert(reads==0);
  sensor.loop();assert(reads==1 && sensor.hasRawCounts());
  hardware=100;
  for(unsigned i=0;i<100;++i) {
    assert(sensor.currentRawCounts()==42);
    assert(sensor.readPreviewValue(OutputMode::RAW,value,unit,sizeof unit) && value==42);
    assert(sensor.readPreviewValue(OutputMode::LINEAR,value,unit,sizeof unit) && value==16);
  }
  assert(reads==1);
  sensor.m_recordRaw=true;now+=1000;sensor.loop();assert(reads==1);
  sensor.publishAcquiredCounts(100,now*1000,0);
  assert(sensor.readPreviewValue(OutputMode::LINEAR,value,unit,sizeof unit) && value==45);
  sensor.publishAcquiredCounts(0,now*1000,0x20);
  assert(!sensor.hasRawCounts() && !sensor.readPreviewValue(OutputMode::RAW,value,unit,sizeof unit));
  sensor.m_recordRaw=false;hardwareValid=false;now+=100;sensor.loop();
  assert(reads==2 && !sensor.hasRawCounts());
}
'''
    fixture=fixture.replace('// ACTUAL_ADAPTER','\n'.join(definition(source,sig) for sig in (
        'void AnalogPotSensor::loop(', 'void AnalogPotSensor::publishAcquiredCounts(',
        'bool AnalogPotSensor::hasRawCounts(', 'int32_t AnalogPotSensor::currentRawCounts(',
        'bool AnalogPotSensor::readPreviewValue(')))
    with tempfile.TemporaryDirectory(prefix='bodaqs-published-counts-') as temp:
        cpp=Path(temp)/'fixture.cpp';cpp.write_text(fixture,encoding='utf-8')
        for index,input_path in enumerate((cpp, root/'test/published_sensor_counts_runtime_fixture.cpp')):
            exe=Path(temp)/f'check{index}.exe'
            subprocess.run([args.compiler,'-std=c++17','-O2','-Wall','-Wextra','-Werror',
                            '-DBODAQS_PRODUCTION_RECORDING=1','-I',str(root/'src'),str(input_path),'-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True)
    print('Published counts: concurrent coherent snapshots and read-only preview/calibration adapters passed')


if __name__=='__main__':
    main()
