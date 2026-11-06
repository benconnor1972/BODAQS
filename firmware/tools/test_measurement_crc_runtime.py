"""Independent zlib vectors for measurement wire and canonical logical CRCs."""
import argparse
import os
import ctypes
from pathlib import Path
import random
import struct
import subprocess
import tempfile
import zlib

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol-dir", type=Path, default=Path(__file__).resolve().parents[1] / "can-fd/common/protocol")
    parser.add_argument("--cc", default="gcc")
    parser.add_argument("--compiler", default="g++")
    args = parser.parse_args()
    if os.name == "nt":
        ctypes.windll.kernel32.SetErrorMode(2)
    rng = random.Random(0x20261105)
    data = bytes(rng.randrange(256) for _ in range(1028))
    wire = [[zlib.crc32(data[align:align+length]) for length in range(1025)] for align in range(4)]
    logical = []
    for align in range(4):
        cases = []
        for length in range(1021):
            cls, direction = length % 5 + 1, length % 2
            node = 255 if cls == 5 else length % 4
            context, object_id = 0xfedcba9876543210 ^ length, 0xfffffffe - length
            prefix = struct.pack("<QIBBBBHH", context, object_id, node, cls, direction, 0, length+4, 0)
            cases.append(zlib.crc32(prefix + data[align:align+length]))
        logical.append(cases)
    def array(rows):
        return "{\n" + ",\n".join("{" + ",".join(f"0x{n:08x}U" for n in row) + "}" for row in rows) + "\n}"
    fixture = '''
    #include <assert.h>
    #include <stdint.h>
    #include <stdio.h>
    #include <string.h>
    #include "bodaqs_fragment_transport.h"
    static const uint8_t data[1028]=DATA;
    static const uint32_t wire[4][1025]=WIRE;
    static const uint32_t logical[4][1021]=LOGICAL;
    int main(void) {
        unsigned align,length;
        assert(bodaqs_measurement_crc(NULL,0)==0);
        assert(bodaqs_measurement_crc((const uint8_t *)"123456789",9)==0xcbf43926U);
        for(align=0;align<4;++align) {
            for(length=0;length<=1024;++length)
                assert(bodaqs_measurement_crc(data+align,length)==wire[align][length]);
            for(length=0;length<=1020;++length) {
                BodaqsFragmentState state;
                memset(&state,0,sizeof state);
                state.context=UINT64_C(0xfedcba9876543210)^length;
                state.object=0xfffffffeU-length;
                state.cls=(uint8_t)(length%5+1);state.direction=(uint8_t)(length%2);
                state.node=state.cls==5?255:(uint8_t)(length%4);
                state.total=(uint16_t)(length+4);
                assert(bodaqs_fragment_checksum(&state,data+align)==logical[align][length]);
            }
        }
        puts("Independent zlib wire/canonical CRC vectors: 8186 checks PASS");
        return 0;
    }
    '''.replace("DATA", "{" + ",".join(map(str, data)) + "}").replace("WIRE", array(wire)).replace("LOGICAL", array(logical))
    with tempfile.TemporaryDirectory(prefix="bodaqs-crc-") as temp:
        for compiler, suffix, standard in [(args.cc, ".c", "c11"),
                                            (args.compiler, ".cpp", "c++17")]:
            source, exe = Path(temp) / ("crc" + suffix), Path(temp) / ("crc" + suffix + ".exe")
            source.write_text(fixture, encoding="utf-8")
            subprocess.run([compiler, "-std="+standard, "-Wall", "-Wextra", "-Werror", "-O2",
                            "-I", str(args.protocol_dir.resolve()), str(source), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
