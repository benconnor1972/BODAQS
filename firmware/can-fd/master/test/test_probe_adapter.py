"""Exercise actual CS/DMA/main owner bodies with bench capacity and real codec."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile
import zlib
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
functions='\n'.join(function(n) for n in ('probe_turnover_epoch','probe_turnover_blocked','arm_spi_slot','probe_publish_reply','probe_early_publish','retire_spi_boundary','service_spi_receive'))
owner=function('service_spi_receive')
functions=functions.replace(owner,owner.replace('uint32_t publish_mask=__get_PRIMASK();',
    'inject_boundary(1); uint32_t publish_mask=__get_PRIMASK();')
    .replace('__set_PRIMASK(publish_mask);','__set_PRIMASK(publish_mask); inject_boundary(2);')
    .replace('gSpiProbe.diagnostic_stats[3]=gSpiProbeBoundaryInfo.boundaries;',
        'gSpiProbe.diagnostic_stats[3]=gSpiProbeBoundaryInfo.boundaries; if(received[3]==BODAQS_PROBE_STATS && (received[13]==2 || (received[13]>=8 && received[13]<=10)))request_snapshot_irq();'))
state=source[source.index('typedef struct {\n    uint32_t boundaries,retire_total_us'):]
state=state[:state.index('/* End probe reply trace state. */')]
fixture=Path(__file__).with_name('probe_adapter_fixture.c').read_text()
oracles=[]
for code,length in enumerate((64,128,256)):
    raw=bytearray(length);raw[:4]=bytes((83,80,1,7));raw[15]=code
    raw[-4:]=zlib.crc32(raw[:-4]).to_bytes(4,'little')
    oracles.append('{'+','.join(str(x) for x in raw)+'}')
fixture=fixture.replace('/* CLOCK_ORACLE */','static const uint8_t clock_oracle[3][256]={'+','.join(oracles)+'};')
queue_state=source[source.index('/* Probe receive turnover state.'):source.index('/* End probe receive turnover state. */')]
with tempfile.TemporaryDirectory() as tmp:
    c=Path(tmp)/'adapter.c';exe=Path(tmp)/'adapter.exe'
    c.write_text(fixture.replace('/* ACTUAL_ADAPTER */',state+'\n'+queue_state+'\n'+functions))
    common=root/'firmware/can-fd/common'
    for mode,trace in ((0,0),(1,0),(0,1),(1,1)):
      for capacity in (1,4):
       for early in (0,1):
        subprocess.run([a.cc,'-std=c11','-Wall','-Wextra','-Werror','-O2','-DBODAQS_SPI_PROBE=1',
            f'-DBODAQS_SPI_PROBE_RX_QUEUE_CAPACITY={capacity}',
            f'-DBODAQS_SPI_PROBE_EARLY_PUBLISH={early}',
            f'-DBODAQS_SPI_PROBE_CRC_TABLE={mode}',f'-DBODAQS_SPI_PROBE_TRACE={trace}','-Wno-pointer-to-int-cast','-I'+str(common/'protocol'),'-I'+str(common/'transport'),str(c),
            str(common/'protocol/bodaqs_spi_probe.c'),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True)
