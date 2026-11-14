"""Independent wire CRC oracle for the matched bulk command/response seam."""
import argparse
import pathlib
import subprocess
import tempfile
import zlib


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', default='g++')
    args = parser.parse_args()
    common = pathlib.Path(__file__).resolve().parents[1] / 'can-fd/common/protocol'
    with tempfile.TemporaryDirectory() as temporary:
        root = pathlib.Path(temporary)
        source = root / 'codec.cpp'
        source.write_text(r'''
#include "bodaqs_measurement.h"
#include <cassert>
#include <cstdio>
int main(int argc,char** argv) {
 assert(argc==3); BodaqsMeasurementSlot s={},out={}; s.kind=14;s.node=255;
 s.context=0x123456789abcdef0ULL;s.body[0]=1;s.body[2]=1;
 uint8_t command[BODAQS_MEASUREMENT_BYTES]={},reply[BODAQS_MEASUREMENT_BYTES]={};
 assert(BODAQS_MEASUREMENT_VERSION==5);
 assert(bodaqs_measurement_encode_request(&s,command,sizeof command));
 assert(bodaqs_measurement_decode_request(command,sizeof command,&out));
 for(unsigned i=128;i<sizeof command;++i)command[i]=uint8_t(i);
 assert(bodaqs_measurement_decode_request(command,sizeof command,&out));
 assert(!bodaqs_measurement_decode_request(command,sizeof command-1,&out));
 command[22]^=1;assert(!bodaqs_measurement_decode_request(command,sizeof command,&out));command[22]^=1;
 command[111]^=3;assert(!bodaqs_measurement_decode_request(command,sizeof command,&out));command[111]^=3;
 command[111]^=3;bodaqs_measurement_put(command+124,bodaqs_measurement_crc(command,124),4);
 assert(!bodaqs_measurement_decode_request(command,sizeof command,&out));command[111]^=3;
 command[70]=1;bodaqs_measurement_put(command+124,bodaqs_measurement_crc(command,124),4);
 assert(!bodaqs_measurement_decode_request(command,sizeof command,&out));command[70]=0;
 bodaqs_measurement_put(command+124,bodaqs_measurement_crc(command,124),4);
 FILE* f=fopen(argv[1],"wb");assert(f);fwrite(command,1,128,f);fclose(f);
 s={};s.kind=2;s.node=2;s.context=7;s.object=9;s.total=20+64*BODAQS_SAMPLE_PAYLOADS;
 for(unsigned i=0;i<s.total;++i)s.body[i]=uint8_t(i*17+3);
 assert(bodaqs_measurement_encode(&s,reply,sizeof reply));
 assert(bodaqs_measurement_decode(reply,sizeof reply,&out));
 assert(out.total==s.total && out.body[s.total-1]==s.body[s.total-1]);
 reply[2]=4;assert(!bodaqs_measurement_decode(reply,sizeof reply,&out));reply[2]=5;
 reply[sizeof reply-21]^=1;assert(!bodaqs_measurement_decode(reply,sizeof reply,&out));reply[sizeof reply-21]^=1;
 reply[sizeof reply-17]^=3;
 bodaqs_measurement_put(reply+sizeof reply-4,bodaqs_measurement_crc(reply,sizeof reply-4),4);
 assert(!bodaqs_measurement_decode(reply,sizeof reply,&out));reply[sizeof reply-17]^=3;
 bodaqs_measurement_put(reply+sizeof reply-4,bodaqs_measurement_crc(reply,sizeof reply-4),4);
 f=fopen(argv[2],"wb");assert(f);fwrite(reply,1,sizeof reply,f);fclose(f);
}
''', encoding='utf-8')
        for size in (512, 1024):
            binary, command, reply = (root / name for name in ('codec.exe', 'command.bin', 'reply.bin'))
            subprocess.run([args.compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                            '-DBODAQS_SPI_MEASUREMENT_V4=1', f'-DBODAQS_SPI_BULK_BYTES={size}',
                            '-I', str(common), str(source), '-o', str(binary)], check=True)
            subprocess.run([str(binary), str(command), str(reply)], check=True)
            for path, extent in ((command, 128), (reply, size)):
                wire = path.read_bytes()
                assert len(wire) == extent
                assert int.from_bytes(wire[-4:], 'little') == zlib.crc32(wire[:-4])
                assert wire[-17] == size // 512
            print(f'bulk {size}: command128/full-response independent CRC, corruption, geometry and extent checks passed')


if __name__ == '__main__':
    main()
