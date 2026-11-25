"""Actual master retention/encoded retirement under excess optional metadata."""
import argparse
import subprocess
import tempfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--compiler',default='g++');a=p.parse_args()
root=Path(__file__).resolve().parents[1];common=root/'can-fd/common/protocol'
with tempfile.TemporaryDirectory(prefix='bodaqs-evidence-margin-') as t:
    exe=Path(t)/'test.exe'
    subprocess.run([a.compiler,'-std=c++17','-O2','-Wall','-Wextra','-Werror',
        '-DBODAQS_SPI_MEASUREMENT_V4=1','-DBODAQS_SPI_BULK_BYTES=512','-I',str(common),
        str(root/'test/evidence_margin_fixture.cpp'),*[str(common/n) for n in ['bodaqs_master_service.c','bodaqs_master_protocol.c','bodaqs_control.c','bodaqs_control_exchange.c']],'-o',str(exe)],check=True)
    for scenario in ['steady','burst']:subprocess.run([str(exe),scenario],check=True)
