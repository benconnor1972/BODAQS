"""Actual GPS acquisition, lifecycle, catalog and normal importer against a receiver model."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from runtime_test_helpers import definition


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', default='g++')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    source=(root/'src/DANF10NGpsSensor.cpp').read_text()
    source=re.sub(r'^#include (?:"(?:BoardSelect|ConfigManager|DebugLog|SensorRegistry|UploadModeManager|WebServerManager)\.h"|<HardwareSerial\.h>|<SparkFun_u-blox_GNSS_v3\.h>)\n','',source,flags=re.M)
    sensor=(root/'src/Sensor.cpp').read_text()
    definitions='\n'.join(definition(sensor,sig) for sig in (
        'const char* outputModeName_(', 'void Sensor::setIncludeRaw(', 'void Sensor::setOutputMode(',
        'void Sensor::setOutputUnitsLabel(', 'bool Sensor::describeColumn(',
        'bool Sensor::describeSensorMetadata(', 'bool Sensor::readPreviewValue('))
    fixture=(root/'test/gps_sensor_runtime_fixture.cpp').read_text().replace('// ACTUAL_SENSOR',source).replace('// ACTUAL_BASE_FUNCTIONS',definitions)
    with tempfile.TemporaryDirectory(prefix='bodaqs-gps-') as folder:
        folder=Path(folder)
        arduino=(root/'test/stubs/Arduino.h').read_text()
        arduino=arduino.replace('class String {\npublic:', 'class String {\npublic:\n    void replace(const char* from,const char* to) {\n      const size_t n=strlen(from);if(!n) return;\n      String result;\n      for(size_t i=0;i<len_;) {\n        if(i+n<=len_ && memcmp(buf_+i,from,n)==0) {result+=to;i+=n;}\n        else {result+=buf_[i];++i;}\n      }\n      *this=result;\n    }\n')
        (folder/'Arduino.h').write_text(arduino)
        for name,text in [('queue',(root/'test/gps_native_stream_runtime_fixture.cpp').read_text()),('sensor',fixture)]:
            cpp=folder/(name+'.cpp');cpp.write_text(text)
            exe=folder/(name+'.exe')
            subprocess.run([args.compiler,'-std=c++17','-Wall','-Wextra','-Wno-unused-parameter','-Wno-unused-variable','-O2',
                '-DBODAQS_PRODUCTION_RECORDING=1','-I',str(folder),'-I',str(root/'test/stubs'),'-I',str(root/'src'),str(cpp),
                str(root/'src/BdqV2Catalog.cpp'),str(root/'src/SensorParams.cpp'),'-o',str(exe)],check=True)
            subprocess.run([str(exe),str(folder/'recording')],check=True)
        sys.path.insert(0,str(root.parent/'analysis/tests'))
        sys.path.insert(0,str(root.parent/'analysis'))
        from test_io_bdq_v2 import FILE_HEADER,FILE_MAGIC_V2,_metadata,_primary_descriptor,_primary_record,_json_chunk,_chunk,_stream_data
        from bodaqs_analysis.pipeline import load_bdq_session
        catalog=json.loads((folder/'recording.catalog.json').read_text());catalog['streams'].insert(0,_primary_descriptor())
        rows=(folder/'recording.records').read_bytes()
        path=folder/'gps.bdq'
        path.write_bytes(FILE_HEADER.pack(FILE_MAGIC_V2,2,0,FILE_HEADER.size,0,0,0)+b''.join([
            _json_chunk(1,0,{**_metadata(),'stream_count':2}),_json_chunk(2,1,catalog),
            _chunk(3,2,_stream_data(1,16,[_primary_record(0,1000,0)],[])),
            _chunk(3,3,_stream_data(2,64,[rows[i:i+64] for i in range(0,len(rows),64)],[]))]))
        session=load_bdq_session(path)
        raw=session['stream_dfs']['gps_native'];engineering=session['stream_dfs']['gps_native_engineering']
        assert list(raw.latitude_e7)==[-319512345]*3
        assert engineering.latitude.iloc[0]==-31.9512345
        assert engineering.longitude.iloc[0]==115.8612345
        assert engineering.latitude.iloc[1:2].isna().all()
        assert engineering.receiver_unix_seconds.iloc[1:].isna().all()
    print('GPS actual receiver adapter, preview, stale/missing/no-fix, STOP/restart, catalog and normal import passed')

if __name__=='__main__':main()
