"""Exercise actual CS/DMA/main owner bodies with bench capacity and real codec."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile
p=argparse.ArgumentParser();p.add_argument('--cc',required=True);a=p.parse_args()
root=Path(__file__).resolve().parents[4]
source=(root/'firmware/can-fd/master/src/main.c').read_text()
def function(name):
    m=re.search(r'static [^;{}]+\b'+name+r'\([^;{}]*\)\s*\{',source)
    assert m,name
    end=m.end();depth=1
    while depth:
        depth+=(source[end]=='{')-(source[end]=='}');end+=1
    return source[m.start():end]
functions='\n'.join(function(n) for n in ('arm_spi_slot','retire_spi_boundary','service_spi_receive'))
owner=function('service_spi_receive')
functions=functions.replace(owner,owner.replace('__DMB();','inject_boundary(1); __DMB();')
    .replace('gSpiTransmitReady=true;','gSpiTransmitReady=true; inject_boundary(2);'))
fixture=Path(__file__).with_name('probe_adapter_fixture.c').read_text()
with tempfile.TemporaryDirectory() as tmp:
    c=Path(tmp)/'adapter.c';exe=Path(tmp)/'adapter.exe'
    c.write_text(fixture.replace('/* ACTUAL_ADAPTER */',functions))
    common=root/'firmware/can-fd/common'
    subprocess.run([a.cc,'-std=c11','-Wall','-Wextra','-Werror','-O2','-DBODAQS_SPI_PROBE=1',
        '-Wno-pointer-to-int-cast','-I'+str(common/'protocol'),'-I'+str(common/'transport'),str(c),
        str(common/'protocol/bodaqs_spi_probe.c'),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
