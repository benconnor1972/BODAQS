"""Independent v1/v2 wire vectors against the production reason and bool APIs."""
import argparse
from pathlib import Path
import subprocess
import tempfile
import zlib


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler',default='g++')
    parser.add_argument('--block-crc',action='store_true')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='bodaqs-decode-reasons-') as directory:
        cpp=Path(directory)/'decode.cpp';exe=Path(directory)/'decode.exe'
        cpp.write_text('''#include "bodaqs_measurement.h"
#include <cstdio>
#include <cstring>
#include <cassert>
int main() {
 uint8_t bytes[BODAQS_MEASUREMENT_BYTES];BodaqsMeasurementSlot a,b;
 while(std::fread(bytes,1,sizeof bytes,stdin)==sizeof bytes) {
  std::memset(&a,0xa5,sizeof a);b=a;
  auto reason=bodaqs_measurement_decode_result(bytes,sizeof bytes,&a);
  const bool valid=bodaqs_measurement_decode(bytes,sizeof bytes,&b);
  assert(valid==(reason==BODAQS_MEASUREMENT_DECODE_OK));assert(!std::memcmp(&a,&b,sizeof a));
  // Independent output contract: header/CRC rejects leave all bytes untouched;
  // later checks occur after the original payload copy, with metadata zero.
  if(reason>=BODAQS_MEASUREMENT_DECODE_MAGIC && reason<=BODAQS_MEASUREMENT_DECODE_CRC) {
   const auto* raw=reinterpret_cast<const unsigned char*>(&a);
   for(unsigned i=0;i<sizeof a;++i) assert(raw[i]==0xa5);
  } else {
   assert(a.kind==bytes[3] && a.context==0 && a.object==0 && a.node==0 && a.total==0);
   assert(!std::memcmp(a.body,bytes+20,BODAQS_MEASUREMENT_BODY_BYTES));
#if BODAQS_MEASUREMENT_VERSION == 2
   assert(!a.retired && a.retiredClass==0 && a.retiredObject==0 && a.retiredTotal==0);
#endif
  }
  std::puts(bodaqs_measurement_decode_name(reason));
 }
 assert(bodaqs_measurement_decode_result(nullptr,0,&a)==BODAQS_MEASUREMENT_DECODE_ARGUMENT);
 assert(bodaqs_measurement_decode_result(bytes,sizeof bytes-1,&a)==BODAQS_MEASUREMENT_DECODE_SIZE);
}
''',encoding='utf-8')
        # Windows binary stdin must preserve embedded0x1a/CR/LF.
        text=cpp.read_text();text=text.replace('#include <cstdio>','#include <cstdio>\n#ifdef _WIN32\n#include <io.h>\n#include <fcntl.h>\n#endif')
        text=text.replace('int main() {','int main() {\n#ifdef _WIN32\n_setmode(_fileno(stdin),_O_BINARY);\n#endif')
        cpp.write_text(text)
        for version,size in ((1,64),(2,256)):
            subprocess.run([args.compiler,'-std=c++17','-Wall','-Wextra','-Werror',f'-DBODAQS_SPI_MEASUREMENT_V2={version-1}',
                *(['-DBODAQS_MASTER_BLOCK_CRC=1'] if args.block_crc else []),
                '-I',str(root/'can-fd/common/protocol'),str(cpp),'-o',str(exe)],check=True)
            valid=bytearray(size);valid[:4]=bytes((0x42,0x4d,version,0))
            def crc(raw):raw[-4:]=zlib.crc32(raw[:-4]).to_bytes(4,'little');return raw
            crc(valid);cases=[(valid,'ok')]
            for offset,value,reason in ((0,0,'magic'),(2,99,'version'),(3,255,'kind'),(size-1,valid[-1]^1,'crc')):
                raw=valid.copy();raw[offset]=value;cases.append((raw,reason))
            if version==2:
                for offset,value,reason in ((239,1,'reserved'),(238,2,'retired_flag'),(247,1,'availability'),
                    (238,1,'retirement'),(236,1,'unexpected_retirement'),(60,1,'padding')):
                    raw=valid.copy();raw[offset]=value;cases.append((crc(raw),reason))
                raw=valid.copy();raw[239]=1;raw[238]=2;raw[247]=1;raw[60]=1
                cases.append((crc(raw),'reserved'))
            actual=subprocess.check_output([str(exe)],input=b''.join(raw for raw,_ in cases)).decode().splitlines()
            assert actual==[reason for _,reason in cases],actual
    print('Actual decode reasons: independent v1/v2 vectors, bool/output equivalence and rejection precedence PASS')


if __name__=='__main__':main()
