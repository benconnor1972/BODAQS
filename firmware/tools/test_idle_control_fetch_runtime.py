"""Real acquisition selector and encoded master requests, including ACK preservation."""
import argparse
from pathlib import Path
import subprocess
import tempfile
from test_remote_imu_lifecycle_runtime import fixture_source

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--compiler',default='g++')
    p.add_argument('--baseline',action='store_true')
    args=p.parse_args();root=Path(__file__).resolve().parents[1]
    fixture=fixture_source(root)
    fixture=fixture.replace('static ParamStore extraParams[7];','[[maybe_unused]] static ParamStore extraParams[7];')
    fixture=fixture.replace('namespace SharedSpiBus {','static std::vector<BodaqsMeasurementSlot> capturedSchedule;\nnamespace SharedSpiBus {',1)
    fixture=fixture.replace(' if(!spiAvailable) return false;', ''' if(!spiAvailable) return false;
 if(length==BODAQS_MEASUREMENT_BYTES) {BodaqsMeasurementSlot r={};assert(bodaqs_measurement_decode(tx,length,&r));capturedSchedule.push_back(r);}''',1)
    fixture += (root/'test/idle_control_fetch_fixture.cpp').read_text(encoding='utf-8')
    protocol=root/'can-fd/common/protocol'
    sources=[*protocol.glob('bodaqs_control*.c'),protocol/'bodaqs_imu_disabled.c',protocol/'bodaqs_master_service.c',protocol/'bodaqs_master_protocol.c']
    sources += [root/'src'/n for n in ('CanMasterProtocol.cpp','SensorAssignment.cpp','SensorParams.cpp','Lsm6dso32xConfig.cpp','RemoteImuStream.cpp','BdqV2Catalog.cpp','ImuAdmission.cpp')]
    with tempfile.TemporaryDirectory(prefix='bodaqs-idle-fetch-') as tmp:
        cpp,exe=Path(tmp)/'fixture.cpp',Path(tmp)/'fixture.exe';cpp.write_text(fixture,encoding='utf-8')
        subprocess.run([args.compiler,'-std=c++17','-DBODAQS_SPI_MEASUREMENT_V2=1',f'-DBODAQS_RECLAIM_IDLE_CONTROL_FETCH={int(not args.baseline)}',
            '-ffunction-sections','-Wl,--gc-sections','-Wall','-Wextra','-Werror','-Wno-class-memaccess','-Wno-unused-function',
            '-I',str(root/'test/stubs'),'-I',str(root/'src'),'-I',str(protocol),'-I',str(root/'can-fd/common/test'),str(cpp),*map(str,sources),'-o',str(exe)],check=True)
        for scenario in ('idle','ack','ordinary','urgent','partial','control-ack','retired-cache','blocked','no-data','fair','partial-data','head-budget','data-fair','timer-wrap'):
            subprocess.run([str(exe),scenario],check=True)

if __name__=='__main__':main()
