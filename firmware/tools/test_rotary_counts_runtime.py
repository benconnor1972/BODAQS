"""Real rotary acquisition/lifecycle/preview methods with independent register I/O."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from runtime_test_helpers import definition

COMMON = (
    'onLoggingStart', 'onLoggingStop', 'onLoggingFinalized', 'startLoggingSession',
    'asyncAcquire', 'asyncSchedulerStarting', 'asyncSchedulerStopped', 'asyncMissedServiceSlots',
    'asyncTargetRateHz', 'readRegBytesLocked_', 'readOutputBlock_', 'readDiagnostics_',
    'refreshDiagnostics_', 'maybeWarnDiagnostics_', 'readRawAngle_', 'readRawAngleOnce_',
    'normalizeCount_', 'signedDeltaCounts_', 'calibrationCountsFromRaw_', 'degreesFromRaw_',
    'resetAsyncSnapshot_', 'publishAsyncSnapshot_', 'copyAsyncSnapshot_', 'acquireAsyncSample_',
    'sampleValues', 'sampleValuesFromAsync_', 'currentRawCounts', 'readPreviewValue',
    'pendingLoggingRows', 'describeBdqV2Stream', 'describeRuntimeDiagnostics',
    'setRuntimeFailure_', 'recordRuntimeEvent_', 'updateReadTransition_', 'resetSessionRuntimeDiagnostics_',
)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler',default='g++')
    args=parser.parse_args();root=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='bodaqs-rotary-') as folder:
        folder=Path(folder)
        arduino=(root/'test/stubs/Arduino.h').read_text(encoding='utf-8')
        arduino=re.sub(r'inline unsigned long millis\(\) \{.*?\n\}',
            'extern uint64_t modelTimeUs;\ninline unsigned long millis(){return modelTimeUs/1000;}',arduino,flags=re.S)
        (folder/'Arduino.h').write_text(arduino,encoding='utf-8')
        for family,cls in [('as5600','AS5600AngleSensor'),('as5048b','AS5048BAngleSensor')]:
            source=(root/f'src/{cls}.cpp').read_text(encoding='utf-8')
            source=subprocess.run([args.compiler,'-E','-P','-x','c++','-DBODAQS_PRODUCTION_RECORDING=1','-'],
                input=re.sub(r'^#include.*$', '', source, flags=re.M),text=True,capture_output=True,check=True).stdout
            header=(root/f'src/{cls}.h').read_text(encoding='utf-8')
            header=header.replace(': public Sensor, public I2CAsyncClient',': public PreviewBase').replace(' override','').replace('private:','public:').replace('#pragma once','').replace(cls,'TestRotary')
            helpers=source[source.index('namespace {'):source.index(f'{cls}::I2CReadMode parseReadMode_')]+ '\n}\n'
            helpers=helpers.replace(cls,'TestRotary')
            if family=='as5600':
                helpers+='\n'+definition(source,'uint16_t decode12_(')+'\n'+definition(source,'uint16_t decode16_(')
            names=list(COMMON)
            if family=='as5600':
                names += ['readRawAngleBytesLocked_','writeRegBytesLocked_','readAngleRegister_',
                          'applyVolatileConfig_','maybeApplyVolatileConfig_','readDeviceConfig_',
                          'maybeRefreshDeviceConfig_','primaryFromRaw_','enqueueBdqV2Record_']
            methods=[]
            for name in names:
                match=re.search(r'^[\w:<>]+ '+cls+r'::'+name+r'\(',source,re.M)
                if not match:raise ValueError(f'missing {cls}::{name}')
                try:
                    methods.append(definition(source,match.group()).replace(cls,'TestRotary'))
                except IndexError:
                    raise ValueError(f'unbalanced extraction: {cls}::{name}')
            methods.append('void TestRotary::begin() { assert(false && "unexpected deferred recovery"); }')
            methods.append('void TestRotary::logFailureProbe_() const {}')
            # Setup is outside the seam: tests begin after board/configuration preparation.
            methods.append('''TestRotary::TestRotary(const Params& p) {
              snprintf(m_name,sizeof m_name,"%s",p.name);m_asyncRateHz=p.asyncRateHz;
              m_zeroCount=p.zeroCount;m_directionSign=p.directionSign;m_includeRaw=false;
              m_wire=&wire;m_diagnosticIntervalMs=0;
#if TEST_AS5600
              m_includeAngleColumn=p.includeAngleColumn;m_slowFilterCode=-1;
              m_deviceConfigReadOk=true;m_configWriteOk=true;
#endif
            }''')
            fixture=(root/'test/rotary_sensor_runtime_fixture.cpp').read_text().replace('// ACTUAL_CLASS',header).replace('// ACTUAL_HELPERS',helpers).replace('// ACTUAL_METHODS','\n'.join(methods))
            if family=='as5600':
                fixture=fixture.replace('// ACTUAL_HELPERS',definition(source,'void recordRuntimeTiming_('))
            cpp=folder/(family+'.cpp');cpp.write_text(fixture,encoding='utf-8')
            exe=folder/(family+'.exe')
            subprocess.run([args.compiler,'-std=c++17','-Wall','-Wno-unused-function','-Wno-unused-variable','-O0',
                '-DBODAQS_PRODUCTION_RECORDING=1',f'-DTEST_AS5600={1 if family=="as5600" else 0}',
                '-I',str(folder),'-I',str(root/'test/stubs'),'-I',str(root/'src'),str(cpp),str(root/'src/BdqV2Catalog.cpp'),'-o',str(exe)],check=True)
            subprocess.run([str(exe),str(folder/family)],check=True)
            check_import(root,folder,family)
        queue=folder/'queue.exe'
        subprocess.run([args.compiler,'-std=c++17','-I',str(root/'src'),str(root/'test/rotary_count_stream_runtime_fixture.cpp'),'-o',str(queue)],check=True)
        subprocess.run([str(queue)],check=True)
    print('Rotary real adapters, I2C registers, observational previews, STOP/restart, queues and normal import passed')


def check_import(root,folder,family):
    sys.path.insert(0,str(root.parent/'analysis/tests'));sys.path.insert(0,str(root.parent/'analysis'))
    from test_io_bdq_v2 import FILE_HEADER,FILE_MAGIC_V2,_metadata,_primary_descriptor,_primary_record,_json_chunk,_chunk,_stream_data
    from bodaqs_analysis.pipeline import load_bdq_session
    catalog=json.loads((folder/(family+'.catalog.json')).read_text());catalog['streams'].insert(0,_primary_descriptor())
    rows=(folder/(family+'.records')).read_bytes();path=folder/(family+'.bdq')
    path.write_bytes(FILE_HEADER.pack(FILE_MAGIC_V2,2,0,FILE_HEADER.size,0,0,0)+b''.join([
        _json_chunk(1,0,{**_metadata(),'stream_count':2}),_json_chunk(2,1,catalog),
        _chunk(3,2,_stream_data(1,16,[_primary_record(0,1000,0)],[])),
        _chunk(3,3,_stream_data(2,32,[rows[i:i+32] for i in range(0,len(rows),32)],[]))]))
    session=load_bdq_session(path)
    raw=session['stream_dfs']['steering_native'];derived=session['stream_dfs']['steering_native_engineering']
    assert list(raw.raw_angle)==[4094 if family=='as5600' else 16382,3,3]
    assert derived.device_angle_deg.iloc[2:].isna().all()
    assert derived.device_angle_deg.iloc[1]==(3*360/(4096 if family=='as5600' else 16384))
    if family=='as5600':assert list(raw.angle_count)==[1234,1234,0]

if __name__=='__main__':main()

