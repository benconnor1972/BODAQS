"""Execute the actual generated-code wrapper; no SDK or device required."""
import argparse
from pathlib import Path
import subprocess
import tempfile


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc',default='gcc');args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='bodaqs-spi-init-') as directory:
        folder=Path(directory)
        (folder/'ti_msp_dl_config.h').write_text('''#pragma once
#include <stdint.h>
typedef struct {uint32_t control,enabled;} SPI_Regs;
extern SPI_Regs selected,other;
#define SPI_A8_INST (&selected)
static inline void DL_SPI_enable(SPI_Regs *spi) {spi->enabled=1;}
void SYSCFG_DL_init(void);
void SYSCFG_DL_SPI_A8_init(void);
''')
        (folder/'ti_msp_dl_config.c').write_text('''#include "ti_msp_dl_config.h"
void SYSCFG_DL_SPI_A8_init(void) {selected.control=0x27;DL_SPI_enable(SPI_A8_INST);}
void SYSCFG_DL_init(void) {SYSCFG_DL_SPI_A8_init();other.control=0x1234;DL_SPI_enable(&other);}
''')
        fixture=folder/'test.c';exe=folder/'test.exe'
        fixture.write_text('''#include "ti_msp_dl_config.h"
#include <assert.h>
#include <stdio.h>
SPI_Regs selected,other;
int main(void) {
 for(unsigned reset=0;reset<3;++reset) {
  selected=(SPI_Regs){0};other=(SPI_Regs){0};SYSCFG_DL_init();
  assert(selected.control==0x27 && other.control==0x1234 && other.enabled==1);
  assert(selected.enabled==!BODAQS_MASTER_SPI_DISABLED_INIT);
  // The macro is local to the wrapper TU: application enable remains real.
  DL_SPI_enable(SPI_A8_INST);assert(selected.enabled==1);
 }
 puts("actual SysConfig wrapper: startup/reinit, selected-only suppression, default and macro isolation PASS");
}
''')
        for enabled in (0,1):
            flags=[f'-DBODAQS_MASTER_SPI_DISABLED_INIT={enabled}']
            if enabled:flags+=['-DBODAQS_MASTER_SPI_TX_PRIME=1','-DBODAQS_SPI_MEASUREMENT_V2=1']
            subprocess.run([args.cc,'-std=c11','-Wall','-Wextra','-Werror','-O2',*flags,
                '-I',str(folder),'-I',str(root/'include'),str(root/'src/master_sysconfig.c'),str(fixture),'-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True)
        for flags in (['-DBODAQS_MASTER_SPI_DISABLED_INIT=2'],['-DBODAQS_MASTER_SPI_DISABLED_INIT=1'],
                      ['-DBODAQS_MASTER_SPI_DISABLED_INIT=1','-DBODAQS_MASTER_SPI_TX_PRIME=1'],
                      ['-DBODAQS_MASTER_SPI_DISABLED_INIT=1','-DBODAQS_MASTER_SPI_TX_PRIME=1','-DBODAQS_SPI_MEASUREMENT_V2=1','-DBODAQS_CAN_SPI_BENCH_MODE=1']):
            result=subprocess.run([args.cc,'-E','-x','c','-I',str(root/'include'),*flags,'-'],
                input='#include "master_spi_initialization.h"\n',text=True,capture_output=True)
            assert result.returncode,'Unsafe initialization control accepted'


if __name__=='__main__':main()
