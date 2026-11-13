"""Exercise window ownership through actual encoded master transfers."""
import argparse
from pathlib import Path
import subprocess
import tempfile
import sys

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler',default='g++')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    common=root/'can-fd/common/protocol'
    with tempfile.TemporaryDirectory(prefix='bodaqs-window-') as tmp:
        exe=Path(tmp)/'window.exe'
        subprocess.run([args.compiler,'-std=c++17','-Wall','-Wextra','-Werror',
            '-DBODAQS_SPI_MEASUREMENT_V4=1','-I',str(common),'-I',str(root/'src'),
            str(root/'test/master_window_fixture.cpp'),
            *[str(common/n) for n in ('bodaqs_master_service.c','bodaqs_master_protocol.c',
                'bodaqs_control.c','bodaqs_control_exchange.c')],
            *[str(root/'src'/n) for n in ('RemoteImuStream.cpp','BdqV2Catalog.cpp','BdqV2Writer.cpp')],
            '-o',str(exe)],check=True)
        recording=Path(tmp)/'four.bdq'
        subprocess.run([str(exe),str(recording)],check=True)
        sys.path.insert(0,str(root.parent/'analysis'))
        from bodaqs_analysis.can_imu_packets import read_can_imu_packets
        for n in range(4):
            decoded=read_can_imu_packets(recording,f'can{n}_imu6')
            assert [r['sequence'] for r in decoded['readings']]==list(range(60))
            assert all([r[k] for k in ('ax','ay','az','gx','gy','gz')]==[4660+n,0,0,0,0,0]
                       for r in decoded['readings'])
            assert not decoded['gaps'] and not decoded['ambiguous_packets']
        print('Four-source master -> RAM custody -> BDQ -> independent exact readings: PASS')
if __name__=='__main__':
    main()
