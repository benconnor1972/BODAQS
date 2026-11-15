"""Poison reused storage; compare valid object bytes and every encoded reply byte."""
import argparse
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', default='g++')
    parser.add_argument('--reference', type=Path)
    args = parser.parse_args()
    common = Path(__file__).resolve().parents[1] / 'can-fd/common/protocol'
    fixture = r'''
#include "bodaqs_master_service.h"
#include "bodaqs_master_profile.h"
#include "bodaqs_master_window.h"
#include <cassert>
#include <cstdio>
static BodaqsMasterService s;
static BodaqsMasterWindowStorage w;
int main() {
 for(unsigned count=1;count<=BODAQS_SAMPLE_PAYLOADS;++count) {
  s={};w={};s.window=&w;s.transfer_context=9;
  // Unit storage survives prior use, including bytes beyond a short object's end.
  for(auto &u:w.units[0])memset(u.bytes,0xa5,sizeof u.bytes);
  auto &q=s.ingress[0];q.count=count;
  for(unsigned i=0;i<count;++i) {
   auto &r=q.records[i];r.boot=5;r.ordinal_high=7;r.received_ms=0;
   for(unsigned j=0;j<64;++j)r.bytes[12+j]=uint8_t(i*31+j);
  }
  window_advance(&s,0,25);
  auto &u=w.units[0][0];assert(u.object.complete && u.count==count);
  assert(u.object.total==20+64*count && !q.count);
  assert(bodaqs_measurement_get(u.bytes,2)==2 && u.bytes[2]==1 && !u.bytes[3]);
  assert(bodaqs_measurement_get(u.bytes+4,4)==5 && bodaqs_measurement_get(u.bytes+8,4)==7);
  assert(bodaqs_measurement_get(u.bytes+12,2)==count && !u.bytes[14] && !u.bytes[15]);
  for(unsigned i=0;i<count;++i)for(unsigned j=0;j<64;++j)
   assert(u.bytes[16+64*i+j]==uint8_t(i*31+j));
  assert(bodaqs_measurement_get(u.bytes+16+64*count,4)==u.object.checksum);
  assert(fwrite(u.bytes,1,u.object.total,stdout)==u.object.total);
  for(unsigned index=0;index*BODAQS_MEASUREMENT_BODY_BYTES<u.object.total;++index) {
   BodaqsMeasurementSlot poisoned,expected;
   memset(&poisoned,0xa5,sizeof poisoned);memset(&expected,0,sizeof expected);
   assert(bodaqs_fragment_emit(&u.object,u.bytes,index,&poisoned));
   const unsigned offset=index*BODAQS_MEASUREMENT_BODY_BYTES;
   unsigned n=u.object.total-offset;if(n>BODAQS_MEASUREMENT_BODY_BYTES)n=BODAQS_MEASUREMENT_BODY_BYTES;
   expected.kind=2;expected.context=9;expected.object=u.object.object;expected.node=0;
   expected.index=index;expected.total=u.object.total;memcpy(expected.body,u.bytes+offset,n);
   // Compare representation too: no stale metadata, padding or tail remains.
   assert(!memcmp(&poisoned,&expected,sizeof expected));
   uint8_t actual[BODAQS_MEASUREMENT_BYTES],oracle[BODAQS_MEASUREMENT_BYTES];
   memset(actual,0x5a,sizeof actual);memset(oracle,0xcc,sizeof oracle);
   assert(bodaqs_measurement_encode(&poisoned,actual,sizeof actual));
   assert(bodaqs_measurement_encode(&expected,oracle,sizeof oracle));
   assert(!memcmp(actual,oracle,sizeof actual));
   assert(fwrite(actual,1,sizeof actual,stdout)==sizeof actual);
  }
 }
 const unsigned lengths[]={4,20,68,96,BODAQS_MEASUREMENT_BODY_BYTES-1,
  BODAQS_MEASUREMENT_BODY_BYTES,BODAQS_MEASUREMENT_BODY_BYTES+1,1024};
 uint8_t data[1024];for(unsigned i=0;i<sizeof data;++i)data[i]=uint8_t(i*13+5);
 for(unsigned cls=1;cls<=5;++cls)for(unsigned length:lengths) {
  BodaqsFragmentState state={};state.complete=1;state.context=17;state.object=3;
  state.node=cls==5?255:1;state.cls=cls;state.total=length;
  for(unsigned index=0;index*BODAQS_MEASUREMENT_BODY_BYTES<length;++index) {
   BodaqsMeasurementSlot actual,expected={};memset(&actual,0x5a,sizeof actual);
   assert(bodaqs_fragment_emit(&state,data,index,&actual));
   unsigned n=length-index*BODAQS_MEASUREMENT_BODY_BYTES;
   if(n>BODAQS_MEASUREMENT_BODY_BYTES)n=BODAQS_MEASUREMENT_BODY_BYTES;
   expected.kind=bodaqs_fragment_kind(cls);expected.node=state.node;expected.context=17;
   expected.object=3;expected.index=index;expected.total=length;
   memcpy(expected.body,data+index*BODAQS_MEASUREMENT_BODY_BYTES,n);
   assert(!memcmp(&actual,&expected,sizeof actual));
   uint8_t wire[BODAQS_MEASUREMENT_BYTES];assert(bodaqs_measurement_encode(&actual,wire,sizeof wire));
   assert(fwrite(wire,1,sizeof wire,stdout)==sizeof wire);
  }
 }
}
'''
    with tempfile.TemporaryDirectory(prefix='bodaqs-bounded-init-') as tmp:
        cpp, exe = Path(tmp) / 'test.cpp', Path(tmp) / 'test.exe'
        cpp.write_text(fixture, encoding='utf-8')
        for size in (0, 512, 1024):
            outputs = []
            for headers in ([args.reference] if args.reference else []) + [common]:
                subprocess.run([args.compiler, '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror',
                                '-Wno-unused-function', '-DBODAQS_SPI_MEASUREMENT_V4=1',
                                f'-DBODAQS_SPI_BULK_BYTES={size}', '-I', str(headers), str(cpp),
                                '-o', str(exe)], check=True)
                outputs.append(subprocess.check_output([str(exe)]))
            assert all(o == outputs[0] for o in outputs)
            print(f'{size or 256}: poisoned short/full objects and complete reply bytes PASS')
            if args.reference:
                print('predecessor valid object/wire bytes identical PASS')


if __name__ == '__main__':
    main()
