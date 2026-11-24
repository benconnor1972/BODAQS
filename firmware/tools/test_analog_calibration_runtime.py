"""Check the real analog calibration adapter against published count/time and disk outcomes."""
import argparse
from pathlib import Path
import subprocess
import tempfile
from runtime_test_helpers import definition


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler',default='g++')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    source=(root/'src/AnalogPotSensor.cpp').read_text(encoding='utf-8')
    methods='\n'.join(definition(source,signature) for signature in (
        'bool AnalogPotSensor::beginCalibration(', 'bool AnalogPotSensor::updateCalibration(',
        'bool AnalogPotSensor::finishCalibration(', 'bool AnalogPotSensor::readPreviewValue('))
    fixture=r'''
#include "Arduino.h"
#include "PublishedSensorCounts.h"
#include "Calibration.h"
#include <cassert>
#include <climits>
#include <cmath>
enum class CalPhase { IDLE, ACTIVE, COMPLETE };
enum class OutputMode { RAW, LINEAR };
static bool mutableConfig=true,saveOk=true;
static unsigned writes=0;
class ConfigManager {
public:
  static bool configurationMutable() {return mutableConfig;}
  static bool saveSensorParamsByName(const char*,const char* const*,const String*,size_t count) {
    if(!saveOk)return false;
    writes+=count;return true;
  }
};
static void copyField_(char* out,size_t capacity,const char* value) {if(capacity)snprintf(out,capacity,"%s",value);}
class AnalogPotSensor {
public:
  void publish(int32_t counts) {m_publishedCounts.publish(counts,1000);}
  bool beginCalibration(CalMode);
  bool updateCalibration(int32_t);
  bool finishCalibration(bool);
  bool readPreviewValue(OutputMode,float&,char*,size_t);
  const char* name()const{return "analog";}
  int32_t currentRawCounts()const{return 500;}
private:
  struct CalState {
    CalMode mode=CalMode::NONE;CalPhase phase=CalPhase::IDLE;
    int32_t min_counts=INT32_MAX,max_counts=INT32_MIN;
    uint32_t started_ms=0,samples=0;
  } cal_;
  int32_t sensor_zero_count_=0,sensor_full_count_=1000,installed_zero_count_=0,m_zero=0,m_full=1000;
  float m_fullMm=100;
  bool m_invert=false,m_muted=false;
  double counts_per_mm_=10;
  PublishedSensorCounts m_publishedCounts;
  char m_outputUnitsLabel[8]="mm";
};
// METHODS
int main() {
  AnalogPotSensor sensor;sensor.publish(500);
  float value;char unit[12];
  assert(sensor.readPreviewValue(OutputMode::LINEAR,value,unit,sizeof unit) && value==50);
  assert(sensor.beginCalibration(CalMode::RANGE));
  assert(sensor.updateCalibration(100) && sensor.updateCalibration(300));
  mutableConfig=false;
  assert(!sensor.finishCalibration(true) && !sensor.beginCalibration(CalMode::ZERO));
  mutableConfig=true;saveOk=false;
  assert(!sensor.finishCalibration(true));
  assert(sensor.readPreviewValue(OutputMode::LINEAR,value,unit,sizeof unit) && value==50 && writes==0);
  saveOk=true;
  assert(sensor.finishCalibration(true) && writes==2);
  assert(sensor.readPreviewValue(OutputMode::LINEAR,value,unit,sizeof unit) && value==250);
  assert(sensor.readPreviewValue(OutputMode::RAW,value,unit,sizeof unit) && value==500);
}
'''.replace('// METHODS',methods)
    with tempfile.TemporaryDirectory(prefix='bodaqs-analog-calibration-')as temp:
        cpp,exe=Path(temp)/'test.cpp',Path(temp)/'test.exe'
        cpp.write_text(fixture,encoding='utf-8')
        subprocess.run([args.compiler,'-std=gnu++2a','-DBODAQS_PRODUCTION_RECORDING=1','-Wall','-Wextra',
                        '-I',str(root/'test/stubs'),'-I',str(root/'src'),str(cpp),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True)


if __name__=='__main__':main()
