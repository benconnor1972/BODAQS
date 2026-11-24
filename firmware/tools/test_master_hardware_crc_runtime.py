"""Real provider with a peripheral seam: independent CRC and ISR preemption oracle."""
import argparse
import ast
from pathlib import Path
import subprocess
import tempfile
import zlib


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', default='g++')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    common = root / 'can-fd/common/protocol'
    master = root / 'can-fd/master'
    invalid = subprocess.run([args.compiler, '-E', '-x', 'c++', '-', '-I', str(common),
                              '-DBODAQS_MASTER_HW_CRC=1', '-DBODAQS_MASTER_CRC_RAM=0'],
                             input='#include "bodaqs_measurement.h"\n', text=True, capture_output=True)
    assert invalid.returncode and 'Hardware CRC requires the RAM software fallback' in invalid.stderr
    with tempfile.TemporaryDirectory(prefix='bodaqs-hw-crc-') as directory:
        temp = Path(directory)
        (temp / 'master_crc_port.h').write_text('''#pragma once
#include <stdbool.h>
#include <stdint.h>
bool master_crc_in_isr(void);
void master_crc_power_init(void);
void master_crc_begin(void);
void master_crc_feed8(uint8_t);
void master_crc_feed32(uint32_t);
uint32_t master_crc_result(void);
''')
        (temp / 'port.cpp').write_text(r'''
#include "master_crc.h"
#include <cassert>
static bool isr,inject;
static unsigned accesses,events,nested;
static uint32_t peripheral;
static void boundary() {
 assert(!isr);++accesses;
 if(inject && ++events%3==0) {
  const unsigned before=accesses;const uint32_t saved=peripheral;
  isr=true;
  assert(bodaqs_master_crc32_parts((const uint8_t *)"1234",4,(const uint8_t *)"56789",5)==0xcbf43926);
  assert(accesses==before && peripheral==saved);++nested;isr=false;
 }
}
bool master_crc_in_isr(void) {return isr;}
void master_crc_power_init(void) {boundary();}
void master_crc_begin(void) {boundary();peripheral=0xffffffff;}
static void byte(uint8_t b) {
 peripheral^=b;for(unsigned i=0;i<8;++i)peripheral=(peripheral>>1)^((peripheral&1)?0xedb88320:0);
}
void master_crc_feed8(uint8_t b) {boundary();byte(b);}
void master_crc_feed32(uint32_t word) {boundary();for(unsigned i=0;i<4;++i)byte(uint8_t(word>>(8*i)));}
uint32_t master_crc_result(void) {boundary();return ~peripheral;}
void set_isr(bool value) {isr=value;}
void set_inject(bool value) {inject=value;}
unsigned nested_count(void) {return nested;}
''')
        driver = temp / 'driver.cpp'
        driver.write_text(r'''
#include "master_crc.h"
#include <cassert>
#include <cstdio>
void set_isr(bool);void set_inject(bool);unsigned nested_count(void);
int main() {
 assert(bodaqs_master_crc32_parts((const uint8_t *)"123456789",9,nullptr,0)==0xcbf43926);
 assert(gMasterCrcInfo.cold_fallback_calls==1);
 bodaqs_master_crc_init();assert(gMasterCrcInfo.enabled && gMasterCrcInfo.version==1);
 bodaqs_master_crc_selftest();assert(gMasterCrcSelfTest.state==2 && gMasterCrcSelfTest.checks==4101 && !gMasterCrcSelfTest.failures);
 uint8_t data[1028];for(unsigned i=0;i<sizeof data;++i)data[i]=uint8_t(i*37+11);
 for(unsigned offset=0;offset<4;++offset)for(unsigned n=0;n<=1024;++n) {
  for(unsigned split: {0U,n/2,n})
   printf("%08x\n",bodaqs_master_crc32_parts(data+offset,split,data+offset+split,n-split));
 }
 set_isr(true);
 assert(bodaqs_measurement_crc(data,508)==bodaqs_master_crc32_parts(data,20,data+20,488));
 set_isr(false);set_inject(true);
 for(unsigned n: {0U,1U,3U,4U,20U,124U,484U,508U,1024U})
  printf("%08x\n",bodaqs_master_crc32_parts(data,20<n?20:n,data+(20<n?20:n),n-(20<n?20:n)));
 assert(nested_count()>10 && gMasterCrcInfo.isr_fallback_calls>10 && gMasterCrcInfo.hardware_calls>12000);
}
'''.replace('#include <cstdio>', '#include <cstdio>\n#include <initializer_list>'))
        table = temp / 'table.cpp'
        table.write_text('#include "master_crc_table.h"\n')
        flags = ['-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror',
                 '-DBODAQS_MASTER_HW_CRC=1', '-DBODAQS_MASTER_CRC_RAM=1', '-DBODAQS_CRC_SELFTEST=1',
                 '-I', str(temp), '-I', str(master / 'include'), '-I', str(common)]
        provider = [str(master / 'src/master_crc.c'), str(temp / 'port.cpp'), str(table)]
        exe = temp / 'test.exe'
        subprocess.run([args.compiler, *flags, str(driver), *provider, '-o', str(exe)], check=True)
        result = subprocess.check_output([str(exe)], text=True)
        actual = [int(v, 16) for v in result.splitlines()]
        data = bytes((i * 37 + 11) & 255 for i in range(1028))
        expected = [zlib.crc32(data[offset:offset+n]) for offset in range(4)
                    for n in range(1025) for _ in range(3)]
        expected += [zlib.crc32(data[:n]) for n in (0,1,3,4,20,124,484,508,1024)]
        assert actual == expected
        print(f'{len(actual)} independent zlib vectors, split/alignment/tail and ISR preemption: PASS')
        # Existing real service fixture: exact output equality with opt-in disabled/enabled.
        tree = ast.parse((root / 'tools/test_ackfetch_direct_runtime.py').read_text())
        direct = next(node.value.value for node in ast.walk(tree)
                      if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'fixture' for t in node.targets)
                      and isinstance(node.value, ast.Constant))
        cases = [(0, (root / 'test/measurement_v2_fixture.cpp').read_text())] + [(size, direct) for size in (512, 1024)]
        for size, original in cases:
            outputs = []
            for enabled in (0, 1):
                wire = temp / f'wire{size}-{enabled}.bin'
                selected = [v.replace('BODAQS_MASTER_HW_CRC=1', f'BODAQS_MASTER_HW_CRC={enabled}') for v in flags]
                extra = provider if enabled else [str(table)]
                source = original
                if enabled:
                    source = '#include "master_crc.h"\nvoid set_inject(bool);\n' + source
                    marker = 'int main(int argc,char** argv) {' if size == 0 else 'int main() {'
                    source = source.replace(marker, marker + '\n bodaqs_master_crc_init();set_inject(true);')
                    end = source.rfind('}')
                    source = source[:end] + 'assert(gMasterCrcInfo.hardware_calls>10 && gMasterCrcInfo.isr_fallback_calls>0);\n' + source[end:]
                cpp = temp / 'wire.cpp'
                cpp.write_text(source)
                geometry = ['-DBODAQS_SPI_MEASUREMENT_V2=1'] if size == 0 else ['-DBODAQS_SPI_MEASUREMENT_V4=1', f'-DBODAQS_SPI_BULK_BYTES={size}']
                subprocess.run([args.compiler, *selected, *geometry, str(cpp), *extra,
                                *[str(common / n) for n in ('bodaqs_master_service.c', 'bodaqs_master_protocol.c',
                                                           'bodaqs_control.c', 'bodaqs_control_exchange.c')],
                                '-o', str(exe)], check=True)
                if size == 0:
                    subprocess.run([str(exe), str(wire)], check=True)
                    outputs.append(wire.read_bytes())
                else:
                    outputs.append(subprocess.check_output([str(exe)]))
            assert outputs[0] == outputs[1]
            print(f'real service {size or 256} hardware/software wire equivalence with ISR injection: PASS')



if __name__ == '__main__':
    main()
