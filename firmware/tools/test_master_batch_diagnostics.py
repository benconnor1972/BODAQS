"""Production-code replay plus diagnostic-on/off wire equivalence (no timing model)."""
import argparse
from pathlib import Path
import subprocess
import tempfile
from read_batch_diagnostics import decode

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--compiler',default='g++')
    args=p.parse_args()
    root=Path(__file__).resolve().parents[1]
    common=root/'can-fd/common/protocol'
    results=[]
    with tempfile.TemporaryDirectory(prefix='bodaqs-batch-diagnostics-') as tmp:
        for enabled in (0,1):
            exe=Path(tmp)/f'batch{enabled}.exe'
            command=[args.compiler,'-std=c++17','-O2','-Wall','-Wextra','-Werror',
                '-DBODAQS_SPI_MEASUREMENT_V2=1','-DBODAQS_MASTER_BOUNDARY_RESERVE=2',
                f'-DBODAQS_MASTER_BATCH_DIAGNOSTICS={enabled}','-I',str(common),
                str(root/'test/master_batch_diagnostics_fixture.cpp'),
                *[str(common/n) for n in ('bodaqs_master_service.c','bodaqs_master_protocol.c','bodaqs_control.c','bodaqs_control_exchange.c')],'-o',str(exe)]
            subprocess.run(command,check=True)
            binary=Path(tmp)/'actual-layout.bin'
            run=subprocess.run([str(exe),*([str(binary)] if enabled else [])],capture_output=True,text=True)
            if run.returncode:
                raise RuntimeError(run.stdout+run.stderr)
            results.append(run.stdout)
            if enabled:
                report=decode(binary.read_bytes())
                lane=report['nodes'][0]['lanes'][0]
                assert lane['sealed']==1 and lane['retired']==1 and lane['mean_records_per_sealed_batch']==13
                assert lane['mean_all_prepared_to_ack_ms']==16 and report['scope']['context']=='9'
    if results[0]!=results[1]:
        raise AssertionError('Observation changed wire bytes or retained populations')
    print(results[1],end='')
    print('PASS: eight actual-code scenarios, seal/ACK/fence/reset checks, wire equivalence, independent binary decoding')

if __name__=='__main__':main()
