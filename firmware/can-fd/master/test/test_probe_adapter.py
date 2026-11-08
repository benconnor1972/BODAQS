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
functions='\n'.join(function(n) for n in ('probe_turnover_epoch','probe_turnover_blocked','arm_spi_slot','retire_spi_boundary','service_spi_receive'))
owner=function('service_spi_receive')
functions=functions.replace(owner,owner.replace('uint32_t publish_mask=__get_PRIMASK();',
    'inject_boundary(1); uint32_t publish_mask=__get_PRIMASK();')
    .replace('__set_PRIMASK(publish_mask);','__set_PRIMASK(publish_mask); inject_boundary(2);')
    .replace('gSpiProbe.diagnostic_stats[3]=gSpiProbeBoundaryInfo.boundaries;',
        'gSpiProbe.diagnostic_stats[3]=gSpiProbeBoundaryInfo.boundaries; if(received[3]==BODAQS_PROBE_STATS && received[13]==2)request_snapshot_irq();'))
state=source[source.index('typedef struct {\n    uint32_t boundaries,retire_total_us'):]
state=state[:state.index('static uint32_t gSpiProbePublishedTick,gSpiProbePublishedEpoch;')+
    len('static uint32_t gSpiProbePublishedTick,gSpiProbePublishedEpoch;')]
fixture=Path(__file__).with_name('probe_adapter_fixture.c').read_text()
queue_state=source[source.index('/* Probe receive turnover state.'):source.index('/* End probe receive turnover state. */')]
with tempfile.TemporaryDirectory() as tmp:
    c=Path(tmp)/'adapter.c';exe=Path(tmp)/'adapter.exe'
    c.write_text(fixture.replace('/* ACTUAL_ADAPTER */',state+'\n'+queue_state+'\n'+functions))
    common=root/'firmware/can-fd/common'
    for mode in (0,1):
      for capacity in (1,4):
        subprocess.run([a.cc,'-std=c11','-Wall','-Wextra','-Werror','-O2','-DBODAQS_SPI_PROBE=1',
            f'-DBODAQS_SPI_PROBE_RX_QUEUE_CAPACITY={capacity}',
            f'-DBODAQS_SPI_PROBE_CRC_TABLE={mode}','-Wno-pointer-to-int-cast','-I'+str(common/'protocol'),'-I'+str(common/'transport'),str(c),
            str(common/'protocol/bodaqs_spi_probe.c'),'-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True)
