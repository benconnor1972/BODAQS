"""Execute the actual manager against a continuous register/data-ready SPI model."""
from pathlib import Path
import re,subprocess,tempfile
r=Path(__file__).resolve().parents[1]
s=re.sub(r'^#include[^\n]*\n','',(r/'src/AnalogInputManager.cpp').read_text(),flags=re.MULTILINE)
f=(r/'test/adc_continuous_runtime_fixture.cpp').read_text()
with tempfile.TemporaryDirectory() as d:
 d=Path(d);(d/'SPI.h').write_text('#pragma once\n#include <stdint.h>\nconstexpr int MSBFIRST=1,SPI_MODE1=1; struct SPISettings{SPISettings(uint32_t,int,int){}};\n')
 cpp=d/'test.cpp';exe=d/'test.exe';cpp.write_text(f.replace('// PRODUCTION_MANAGER',s))
 subprocess.run(['C:/msys64/ucrt64/bin/g++.exe','-std=gnu++2a','-Wall','-Wextra','-Werror','-Wno-unused-variable','-Wno-unused-function','-Wno-unused-parameter','-DADC_TEST_ASYNC=0','-DADC_TEST_WREG_STARTS=0','-DBODAQS_ADC_CONTINUOUS_LATEST=1','-DBODAQS_ADC_SPI_PHASE_TIMING=1','-I',str(d),'-I',str(r/'test/stubs'),'-I',str(r/'src'),str(cpp),str(r/'src/SensorParams.cpp'),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True)
s=(r/'src/LoggingManager.cpp').read_text()
assert s.index('if(!AnalogInputManager::continuousHealthy())return false;')<s.index('// --------- Enqueue for StorageManager_loop()')
assert 'stop(StopReason::StartFailure,"adc_continuous_start")' in s
assert s.index('s_sampleInProgress.store(false);',s.index('(void)sampleOnce_();'))<s.index('"adc_continuous_fault"')
print('Faulted results suppressed before enqueue; fault STOP occurs outside row guard PASS; SPI model is not hardware proof')
