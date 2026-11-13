"""Equal live sources retain progress while exact RAM-retirement proofs lag."""
import argparse
from pathlib import Path
import subprocess
import tempfile


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler',default='g++')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    fixture=(root/'test/measurement_runtime_fixture.cpp').read_text(encoding='utf-8')
    fixture=fixture[:fixture.index('int main() {')]
    manager=(root/'src/CanMasterManager.cpp').read_text(encoding='utf-8')
    headers=('Arduino.h','SPI.h','esp_system.h','DebugLog.h','LoggingManager.h','SensorManager.h','SharedSpiBus.h')
    manager='\n'.join(line for line in manager.splitlines() if not any(
        line in ('#include <'+h+'>','#include "'+h+'"') for h in headers))
    fixture=fixture.replace('// PRODUCTION_MANAGER',manager)
    fixture=fixture.replace('namespace SharedSpiBus {',
        'static unsigned fairnessLoseEvery=0,fairnessWireTurns=0;\nnamespace SharedSpiBus {',1)
    fixture=fixture.replace('const auto slotResult=bodaqs_master_service_process_transfer(&master,tx,length,clockMs,next);',
        'if(fairnessLoseEvery && length==BODAQS_MEASUREMENT_BYTES && ++fairnessWireTurns%fairnessLoseEvery==0) return true;\n'
        'const auto slotResult=bodaqs_master_service_process_transfer(&master,tx,length,clockMs,next);')
    fixture+=(root/'test/window_ack_fairness_fixture.cpp').read_text(encoding='utf-8')
    common=root/'can-fd/common/protocol'
    sources=[*common.glob('bodaqs_control*.c'),common/'bodaqs_imu_disabled.c',
        common/'bodaqs_master_service.c',common/'bodaqs_master_protocol.c',
        *[root/'src'/name for name in ('CanMasterProtocol.cpp','SensorAssignment.cpp',
            'SensorParams.cpp','Lsm6dso32xConfig.cpp')]]
    with tempfile.TemporaryDirectory(prefix='bodaqs-ack-fairness-') as tmp:
        cpp,exe=Path(tmp)/'fairness.cpp',Path(tmp)/'fairness.exe'
        cpp.write_text(fixture,encoding='utf-8')
        subprocess.run([args.compiler,'-std=c++17','-DBODAQS_SPI_MEASUREMENT_V4=1',
            '-ffunction-sections','-Wl,--gc-sections','-Wall','-Wextra','-Werror',
            '-Wno-class-memaccess','-Wno-unused-function','-I',str(root/'test/stubs'),
            '-I',str(root/'src'),'-I',str(common),'-I',str(root/'can-fd/common/test'),
            str(cpp),*map(str,sources),'-o',str(exe)],check=True)
        for lag,loss in ((3,0),(2,0),(4,0),(3,5),(2,5),(1,0),(1,2)):
            subprocess.run([str(exe),str(lag),str(loss)],check=True)


if __name__=='__main__':
    main()
