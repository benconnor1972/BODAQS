"""Actual rotary calibration adapters against independent locking/storage models."""
import argparse
from pathlib import Path
import subprocess
import tempfile

from runtime_test_helpers import definition


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', default='g++')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    for family, modulus in [('AS5600', 4096), ('AS5048B', 16384)]:
        cls = family + 'AngleSensor'
        source = (root / 'src' / (cls + '.cpp')).read_text(encoding='utf-8')
        actual = '\n'.join(definition(source, signature).replace(cls + '::', 'TestRotary::')
                           for signature in [f'bool {cls}::beginCalibration(',
                                             f'bool {cls}::updateCalibration(',
                                             f'bool {cls}::finishCalibration(',
                                             f'int32_t {cls}::normalizeCount_('])
        fixture = r'''
#include <cassert>
#include <cstdint>
#include <climits>
#include <string>
struct String:std::string {using std::string::string;explicit String(int32_t value):std::string(std::to_string(value)) {}};
enum class CalMode {NONE,ZERO};enum class CalPhase {IDLE,ACTIVE,COMPLETE};
constexpr int32_t kCountsPerTurn=MODULUS;
constexpr int32_t kDirectionMinDeltaCounts=kCountsPerTurn/720;
static uint32_t millis() {return 123;}
static const char* directionName_(int sign) {return sign<0?"counts_decrease_positive":"counts_increase_positive";}
namespace LoggingManager {static bool locked=false;bool configurationLocked() {return locked;}}
namespace ConfigManager {
  static bool succeed=true;static unsigned writes=0;
  static String savedZero="old",savedDirection="old";
  bool saveSensorParamsByName(const char*,const char* const* keys,const String* values,size_t count) {
    ++writes;assert(count==2 && std::string(keys[0])=="zero_count" && std::string(keys[1])=="direction");
    if(!succeed) return false;savedZero=values[0];savedDirection=values[1];return true;
  }
}
class TestRotary {
public:
  struct CalState {CalMode mode=CalMode::NONE;CalPhase phase=CalPhase::IDLE;
    int32_t first_counts=INT32_MAX,second_counts=INT32_MIN;uint32_t started_ms=0,samples=0;};
  CalState cal_;int32_t m_zeroCount=100,m_calLastUnwrapped=0,current=123;
  int8_t m_directionSign=1;bool m_calUnwrapInit=false;
  const char* name() const {return "steering";}int32_t currentRawCounts() const {return current;}
  bool beginCalibration(CalMode);bool updateCalibration(int32_t);bool finishCalibration(bool);
  static int32_t normalizeCount_(int32_t);
};
// ACTUAL
int main() {
  TestRotary sensor;
  LoggingManager::locked=true;assert(!sensor.beginCalibration(CalMode::ZERO));
  LoggingManager::locked=false;assert(sensor.beginCalibration(CalMode::ZERO));
  assert(!sensor.updateCalibration(INT32_MIN));assert(sensor.cal_.samples==0);
  assert(sensor.updateCalibration(kCountsPerTurn-4));assert(sensor.updateCalibration(kCountsPerTurn-104));
  LoggingManager::locked=true;assert(!sensor.finishCalibration(true));assert(ConfigManager::writes==0);
  LoggingManager::locked=false;ConfigManager::succeed=false;
  assert(!sensor.finishCalibration(true));assert(sensor.m_zeroCount==100 && sensor.m_directionSign==1);
  assert(sensor.cal_.phase==CalPhase::ACTIVE && ConfigManager::savedZero=="old");
  ConfigManager::succeed=true;assert(sensor.finishCalibration(true));
  assert(sensor.m_zeroCount==kCountsPerTurn-4 && sensor.m_directionSign==-1);
  assert(ConfigManager::savedZero==std::to_string(kCountsPerTurn-4));
  assert(ConfigManager::savedDirection=="counts_decrease_positive");
  assert(sensor.beginCalibration(CalMode::ZERO));assert(sensor.updateCalibration(100));
  assert(sensor.updateCalibration(101));assert(!sensor.finishCalibration(true));
  assert(sensor.m_zeroCount==kCountsPerTurn-4);
  assert(sensor.beginCalibration(CalMode::ZERO));sensor.current=INT32_MIN;
  assert(!sensor.finishCalibration(true));
}
'''.replace('MODULUS', str(modulus)).replace('// ACTUAL', actual)
        with tempfile.TemporaryDirectory(prefix='bodaqs-rotary-cal-') as temp:
            cpp = Path(temp) / 'fixture.cpp'
            exe = Path(temp) / 'fixture.exe'
            cpp.write_text(fixture, encoding='utf-8')
            subprocess.run([args.compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                            '-Wno-misleading-indentation', str(cpp), '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True)
    print('Both rotary calibration adapters: locking, unavailable snapshots and atomic-save failure passed')


if __name__ == '__main__':
    main()
