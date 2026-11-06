"""Independent zlib oracle plus byte-for-byte engine traces for both CRC builds."""
import argparse
import ctypes
import _ctypes
import os
from pathlib import Path
import random
import subprocess
import tempfile
import zlib


BRIDGE=r'''
#include <assert.h>
#include <string.h>
#include "bodaqs_spi_probe.h"
unsigned probe_trace(uint8_t *out,unsigned capacity) {
    BodaqsSpiProbeEngine e;bodaqs_spi_probe_init(&e);
    uint8_t tx[256],rx[256];unsigned used=0;
    for(unsigned bytes=64;bytes<=256;bytes*=2) {
        BodaqsSpiProbeFrame q={.opcode=BODAQS_PROBE_BEGIN,.case_id=bytes,
            .profile=bodaqs_spi_probe_profile(bytes,8000000,4)},r;
        assert(bodaqs_spi_probe_encode(&q,tx,bytes));
        assert(bodaqs_spi_probe_process(&e,tx,bytes,rx,256));
        assert(used+bytes<=capacity);memcpy(out+used,rx,bytes);used+=bytes;
        for(unsigned node=0;node<4;++node)for(unsigned object=1;object<=3;++object) {
            q.node=node;q.object_id=object;q.logical_crc=0;q.opcode=BODAQS_PROBE_POLL;
            for(unsigned f=0;f<bodaqs_spi_probe_fragment_count(q.profile);++f) {
                q.fragment=f;
                for(unsigned repeat=0;repeat<2;++repeat) {
                    assert(bodaqs_spi_probe_encode(&q,tx,bytes));
                    assert(bodaqs_spi_probe_process(&e,tx,bytes,rx,256));
                    assert(bodaqs_spi_probe_decode(rx,bytes,&r));
                    assert(used+bytes<=capacity);memcpy(out+used,rx,bytes);used+=bytes;
                }
            }
            q.fragment=0;q.opcode=BODAQS_PROBE_ACK;q.logical_crc=r.logical_crc;
            for(unsigned repeat=0;repeat<2;++repeat) {
                assert(bodaqs_spi_probe_encode(&q,tx,bytes));
                assert(bodaqs_spi_probe_process(&e,tx,bytes,rx,256));
                assert(used+bytes<=capacity);memcpy(out+used,rx,bytes);used+=bytes;
            }
        }
        q.node=0;q.object_id=0;q.logical_crc=0;q.fragment=0;q.opcode=BODAQS_PROBE_STOP;
        assert(bodaqs_spi_probe_encode(&q,tx,bytes));
        assert(bodaqs_spi_probe_process(&e,tx,bytes,rx,256));
        assert(used+bytes<=capacity);memcpy(out+used,rx,bytes);used+=bytes;
    }
    return used;
}
'''


def main():
    p=argparse.ArgumentParser();p.add_argument('--cc',required=True);a=p.parse_args()
    common=Path(__file__).resolve().parents[2]/'common/protocol'
    rng=random.Random(702)
    vectors=[b'',b'123456789',bytes(range(256))]
    vectors += [bytes([v]) for v in range(256)]
    vectors += [bytes(rng.randrange(256) for _ in range(n)) for n in range(1025)]
    with tempfile.TemporaryDirectory(prefix='bodaqs-crc-equivalence-') as tmp:
        tmp=Path(tmp);bridge=tmp/'bridge.c';bridge.write_text(BRIDGE,encoding='utf-8')
        traces=[]
        for mode in (0,1):
            dll=tmp/f'crc{mode}.dll'
            subprocess.run([a.cc,'-std=c11','-O2','-Wall','-Wextra','-Werror','-shared',
                *(['-fPIC'] if os.name!='nt' else []),
                '-DBODAQS_SPI_PROBE=1',f'-DBODAQS_SPI_PROBE_CRC_TABLE={mode}',
                '-I'+str(common),str(common/'bodaqs_spi_probe.c'),str(bridge),'-o',str(dll)],check=True)
            lib=ctypes.CDLL(str(dll))
            lib.bodaqs_spi_probe_crc.argtypes=[ctypes.c_void_p,ctypes.c_size_t]
            lib.bodaqs_spi_probe_crc.restype=ctypes.c_uint32
            for v in vectors:
                assert lib.bodaqs_spi_probe_crc(v,len(v))==zlib.crc32(v),(mode,len(v))
            lib.bodaqs_spi_probe_known_crc.argtypes=[ctypes.c_uint32,ctypes.c_uint8,ctypes.c_uint32]
            lib.bodaqs_spi_probe_known_crc.restype=ctypes.c_uint32
            for case in (1,702,4294967295):
                for node in range(4):
                    for obj in (1,2,4294967295):
                        data=bytes((case*17+node*29+obj*37+i*13+(i>>8)*7)&255 for i in range(1008))
                        assert lib.bodaqs_spi_probe_known_crc(case,node,obj)==zlib.crc32(data)
            lib.probe_trace.argtypes=[ctypes.c_void_p,ctypes.c_uint]
            lib.probe_trace.restype=ctypes.c_uint
            out=ctypes.create_string_buffer(400000);n=lib.probe_trace(out,len(out));traces.append(out.raw[:n])
            if os.name=='nt':_ctypes.FreeLibrary(lib._handle)
            else:_ctypes.dlclose(lib._handle)
        assert traces[0]==traces[1]
    print(f'CRC equivalence: {len(vectors)} independent zlib vectors and36 synthetic object CRCs per mode; {len(traces[0])} identical engine wire bytes PASS')


if __name__=='__main__':main()
