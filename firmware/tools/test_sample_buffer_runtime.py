"""Real four-stream custody at capacity, retry, wrap/refill and allocation failure."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--compiler',required=True)
p.add_argument('--selected-only',action='store_true')
a=p.parse_args();firmware=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as temp:
    reports=[]
    for capacity,extra in [(128,[]),(512,['-DBODAQS_LOGGER_SAMPLE_QUEUE_CAPACITY=512'])]:
        if a.selected_only and capacity!=512:continue
        exe=Path(temp)/f'buffer{capacity}.exe'
        command=[a.compiler,'-std=c++17','-Wall','-Wextra','-Werror',
            '-DBODAQS_SPI_MEASUREMENT_V4=1','-DBODAQS_SPI_BULK_BYTES=512',
            '-DBODAQS_V4_FOUR_NODE_BENCH=1','-DBODAQS_IMU_FLOW_DIAGNOSTICS=1',
            '-DBODAQS_QUEUE_ALLOCATION_TEST',*extra,'-I',str(firmware/'src'),
            str(firmware/'test/sample_buffer_fixture.cpp'),str(firmware/'src/RemoteImuStream.cpp'),'-o',str(exe)]
        subprocess.run(command,check=True)
        result=subprocess.check_output([str(exe),str(capacity)],text=True)
        print(result,end='');reports.append(int(re.search(r'bytes_per_node=(\d+)',result)[1]))
    if len(reports)==2:assert reports[1]-reports[0]==198144
    for capacity,bulk,four in [(256,512,1),(512,0,1),(512,512,0)]:
        result=subprocess.run([a.compiler,'-std=c++17','-fsyntax-only',
            '-DBODAQS_SPI_MEASUREMENT_V4=1',f'-DBODAQS_SPI_BULK_BYTES={bulk}',
            f'-DBODAQS_V4_FOUR_NODE_BENCH={four}',
            f'-DBODAQS_LOGGER_SAMPLE_QUEUE_CAPACITY={capacity}',
            str(firmware/'src/RemoteImuStream.cpp')],capture_output=True,text=True)
        assert result.returncode and 'Logger sample buffer override requires' in result.stderr
print('Real stream capacity, duplicate/blocked retry, FIFO wrap, exact bytes, release/reset, reservation delta and allocation failure PASS')
print('Invalid capacity, bulk scope and four-node scope rejected at compile time: PASS')
