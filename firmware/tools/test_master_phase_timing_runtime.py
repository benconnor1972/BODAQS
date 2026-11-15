"""Compare production v2 wire output with optional phase timing enabled/disabled."""
import argparse
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    common = root / "can-fd/common/protocol"
    original = (root / "test/measurement_v2_fixture.cpp").read_text()
    original = original.replace("int main(", "int exercise(")
    end = original.rfind("}")
    original = original[:end] + "return 0;\n" + original[end:]
    hooks = '''
#include "bodaqs_master_profile.h"
extern "C" void bodaqs_master_work_record(unsigned,uint32_t) {}
extern "C" void bodaqs_master_dispatch_record(uint32_t manage,uint32_t transfer,uint32_t hints,uint8_t,uint8_t) {
 assert(manage==17 && transfer>=17 && transfer%17==0 && hints==17);
}
static unsigned profileRecords, ackFetchRecords, emptyRecords, dataRecords;
static uint32_t profileClock=0xffffffd0u;
extern "C" uint32_t bodaqs_master_profile_clock(void) {profileClock+=17;return profileClock;}
extern "C" void bodaqs_master_profile_record(uint32_t decode,uint32_t dispatch,uint32_t encode,
 uint8_t request,uint8_t reply) {
 assert(decode==17 && dispatch>=51 && dispatch%17==0 && encode==17);
 ++profileRecords;ackFetchRecords+=request==14;emptyRecords+=reply==0;dataRecords+=reply==2;
}
'''
    with tempfile.TemporaryDirectory(prefix="bodaqs-master-phases-") as temp:
        temp = Path(temp)
        results = []
        for enabled, block_crc in ((0,0), (1,0), (0,1), (1,1)):
            cpp, exe, wire = (temp / f"fixture{enabled}-{block_crc}{suffix}" for suffix in (".cpp", ".exe", ".bin"))
            wrapper = '\nint main(int argc,char**argv) {assert(argc==2);exercise(argc,argv);'
            # Existing fixture takes a path argument and writes one independent wire vector.
            if enabled:
                wrapper += 'assert(profileRecords>10 && ackFetchRecords && emptyRecords && dataRecords);'
            wrapper += 'return 0;}\n'
            cpp.write_text(original + (hooks if enabled else "") + wrapper)
            subprocess.run([args.compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-O2",
                            "-DBODAQS_SPI_MEASUREMENT_V2=1", f"-DBODAQS_MASTER_PHASE_TIMING={enabled}",
                            f"-DBODAQS_MASTER_BLOCK_CRC={block_crc}",
                            "-I", str(common), str(cpp), *[str(common / name) for name in
                            ("bodaqs_master_service.c", "bodaqs_master_protocol.c", "bodaqs_control.c", "bodaqs_control_exchange.c")],
                            "-o", str(exe)], check=True)
            subprocess.run([str(exe), str(wire)], check=True)
            results.append(wire.read_bytes())
        assert all(result == results[0] for result in results)
        print("production phase boundaries/wrap and enabled/disabled wire equivalence: PASS")


if __name__ == "__main__":
    main()
