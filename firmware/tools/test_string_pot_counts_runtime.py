"""Real count sensor/queue/catalog through normal import, with independent I/O."""
import argparse
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

from runtime_test_helpers import definition


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler',default='g++')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    source=(root/'src/AS5600StringPotSensorBase.cpp').read_text(encoding='utf-8').replace('#include "ConfigManager.h"','')
    sensor=(root/'src/Sensor.cpp').read_text(encoding='utf-8')
    definitions='\n'.join(definition(sensor,sig) for sig in (
        'const char* outputModeName_(', 'void Sensor::setIncludeRaw(', 'void Sensor::setOutputMode(',
        'void Sensor::setOutputUnitsLabel(', 'bool Sensor::describeColumn(',
        'bool Sensor::describeSensorMetadata(', 'bool Sensor::readPreviewValue('))
    fixture=(root/'test/string_pot_sensor_runtime_fixture.cpp').read_text(encoding='utf-8')
    fixture=fixture.replace('// ACTUAL_SENSOR',source).replace('// ACTUAL_BASE_FUNCTIONS',definitions)
    i2c=(root/'src/AS5600StringPotI2C.cpp').read_text(encoding='utf-8')
    i2c_header=(root/'src/AS5600StringPotI2C.h').read_text(encoding='utf-8')
    fixture=fixture.replace('// ACTUAL_I2C_SNAPSHOT',definition(i2c_header,'  struct AsyncSnapshot {')+';')
    fixture=fixture.replace('// ACTUAL_I2C_ACQUISITION',definition(i2c,'bool AS5600StringPotI2C::acquireAsyncSample_(').replace('AS5600StringPotI2C::','TestI2C::'))
    fixture=fixture.replace('// ACTUAL_I2C_SAMPLING',definition(i2c,'void AS5600StringPotI2C::sampleValues(').replace('AS5600StringPotI2C::','TestI2C::'))
    fixture=fixture.replace('// ACTUAL_I2C_MISSED_SLOTS',definition(i2c,'void AS5600StringPotI2C::asyncMissedServiceSlots(').replace('AS5600StringPotI2C::','TestI2C::'))
    with tempfile.TemporaryDirectory(prefix='bodaqs-string-pot-') as temp:
        temp=Path(temp)
        for name,input_source in (('stream',(root/'test/string_pot_count_stream_runtime_fixture.cpp').read_text()),('sensor',fixture)):
            cpp=temp/(name+'.cpp');cpp.write_text(input_source,encoding='utf-8')
            exe=temp/(name+'.exe')
            subprocess.run([args.compiler,'-std=c++17','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-O2',
                '-DBODAQS_PRODUCTION_RECORDING=1','-I',str(root/'test/stubs'),'-I',str(root/'src'),
                str(cpp),str(root/'src/BdqV2Catalog.cpp'),'-o',str(exe)],check=True)
            subprocess.run([str(exe),str(temp/'recording')] if name=='sensor' else [str(exe)],check=True)
        # Independent file envelope: actual native catalog/bytes are the input.
        sys.path.insert(0,str(root.parent/'analysis/tests'))
        sys.path.insert(0,str(root.parent/'analysis'))
        from test_io_bdq_v2 import FILE_HEADER,FILE_MAGIC_V2,_metadata,_primary_descriptor,_primary_record,_json_chunk,_chunk,_stream_data
        from bodaqs_analysis.pipeline import load_bdq_session
        catalog=json.loads((temp/'recording.catalog.json').read_text())
        descriptor=catalog['streams'][0];catalog['streams'].insert(0,_primary_descriptor())
        assert descriptor['acquisition']['payload_schema']=='bodaqs.string_pot_counts.v1'
        assert descriptor['acquisition']['quality_flags']['settling_held']==2
        metadata={**_metadata(),'stream_count':2,'recording_configuration':{
            'schema':'bodaqs.recording_configuration.v1','sensors':[{
                'sensor_id':'travel','sensor_type':'as5600_string_pot_analog','stream_key':'travel_counts',
                'raw_fields':['wrapped_count','unwrapped_count'],'count_domain':{'id':'string_pot_counts_v1'},
                'calibration':{'model':'string_pot_geometry_v1','available':True,'installed_zero_count':0,
                               'sensor_zero_count':0,'sensor_full_count':4096,'sensor_full_travel':100,
                               'invert':False,'output_unit':'mm'}}]}}
        rows=(temp/'recording.records').read_bytes();assert len(rows)==96
        path=temp/'counts.bdq'
        path.write_bytes(FILE_HEADER.pack(FILE_MAGIC_V2,2,0,FILE_HEADER.size,0,0,0)+b''.join([
            _json_chunk(1,0,metadata),_json_chunk(2,1,catalog),
            _chunk(3,2,_stream_data(1,16,[_primary_record(0,1000,0)],[])),
            _chunk(3,3,_stream_data(2,24,[rows[i:i+24] for i in range(0,96,24)],[]))]))
        session=load_bdq_session(path)
        raw=session['stream_dfs']['travel_counts'];engineering=session['stream_dfs']['travel_counts_engineering']
        assert list(raw.unwrapped_count)==[4090,4090,4090,4099]
        assert engineering.displacement.iloc[0]==99.853515625
        assert engineering.displacement.iloc[1:3].isna().all()
        assert engineering.displacement.iloc[3]==100.0732421875
    print('String-pot count stream, real sensor adapter, preview equivalence and normal import passed')


if __name__=='__main__':
    main()
