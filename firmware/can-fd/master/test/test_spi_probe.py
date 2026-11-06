"""Bench public codec/engine contract; target adapter exercised separately."""
from pathlib import Path
import argparse
import subprocess
import tempfile
p=argparse.ArgumentParser()
p.add_argument('--cc',required=True)
a=p.parse_args()
root=Path(__file__).resolve().parents[4]
common=root/'firmware/can-fd/common/protocol'
with tempfile.TemporaryDirectory() as tmp:
    for mode in (0,1):
        exe=Path(tmp)/f'probe{mode}.exe'
        subprocess.run([a.cc,'-std=c11','-O2','-Wall','-Wextra','-Werror',
            '-DBODAQS_SPI_PROBE=1',f'-DBODAQS_SPI_PROBE_CRC_TABLE={mode}','-I'+str(common),str(common/'bodaqs_spi_probe.c'),
            str(Path(__file__).with_suffix('.c')),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True)
