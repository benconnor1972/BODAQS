"""Check the actual variable-width raw enqueue/pop adapter and loss markers."""
import argparse
from pathlib import Path
import subprocess
import tempfile

from runtime_test_helpers import definition


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = (root / "src/StorageManager.cpp").read_text(encoding="utf-8")
    fixture = r'''
#include "RawAdcRecording.h"
#include "DynamicSpscQueue.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <initializer_list>
bool loggingActive=true;
RawAdcRecordingStats rawStats;
RawAdcRecordingStats* s_rawAdc=&rawStats;
uint16_t s_primaryPendingStatus=0,s_qMax=0;
uint32_t s_rowsFormatFailed=0,s_samplesDropped=0,s_bdqV2MarkEventsDropped=0;
struct Schema {unsigned width=0;unsigned recordSizeBytes()const{return width;}} s_bdqV2PrimarySchema;
DynamicSpscRecordQueue s_bdqV2PrimaryQueue;
struct BdqV2PendingMark {uint64_t hostMonotonicUs=0;uint32_t primarySequence=0;};
struct Marks {BdqV2PendingMark last;bool push(const BdqV2PendingMark& m){last=m;return true;}}s_bdqV2Marks;
// ADAPTER
int main() {
  for(unsigned columns:{0u,1u,2u,3u,8u,32u}) {
    rawStats={};rawStats.active=true;s_primaryPendingStatus=0;s_bdqV2MarkEventsDropped=0;
    s_bdqV2PrimarySchema.width=RawAdcRecording::recordBytes(columns);
    assert(s_bdqV2PrimaryQueue.allocate(s_bdqV2PrimarySchema.width,2));
    RawAdcRecord row;row.sequence=0x12345678;row.tick=0x11223344;
    for(unsigned i=0;i<columns;++i)row.counts[i]=uint16_t(200+i*73);
    assert(StorageManager_enqueueRawAdc(row,true,99,100));
    assert(s_bdqV2Marks.last.hostMonotonicUs==99 && s_bdqV2Marks.last.primarySequence==row.sequence);
    assert(StorageManager_enqueueRawAdc(row,false,0,100));
    assert(!StorageManager_enqueueRawAdc(row,true,101,100));
    assert(s_bdqV2MarkEventsDropped==1); // primary rejection must account for its consumed mark
    uint8_t bytes[sizeof(row)+4];memset(bytes,0xcd,sizeof(bytes));
    assert(!popBdqV2PrimaryRecord_(nullptr,bytes,s_bdqV2PrimarySchema.width-1));
    assert(popBdqV2PrimaryRecord_(nullptr,bytes,sizeof(bytes)));
    assert(bytes[0]==0x78 && bytes[3]==0x12 && bytes[4]==0x44 && bytes[7]==0x11);
    for(unsigned i=0;i<columns;++i)assert(unsigned(bytes[12+2*i])+(unsigned(bytes[13+2*i])<<8)==200+i*73);
    for(unsigned i=s_bdqV2PrimarySchema.width;i<sizeof(bytes);++i)assert(bytes[i]==0xcd);
    assert(StorageManager_enqueueRawAdc(row,false,0,100));
    assert(popBdqV2PrimaryRecord_(nullptr,bytes,sizeof(bytes)));
    assert(!(bytes[8]&3));
    assert(popBdqV2PrimaryRecord_(nullptr,bytes,sizeof(bytes)));
    assert((bytes[8]&3)==3); // next retained row proves the overflow gap
    assert(rawStats.enqueued==3 && rawStats.encoded==3 && rawStats.rejected==1);
    row.reserved=1;
    assert(!StorageManager_enqueueRawAdc(row,false,0,100));
    assert(!s_bdqV2PrimaryQueue.size());
  }
  puts("Typed raw queue: dynamic widths, byte contract, marks, overflow evidence and invalid records passed");
}
'''.replace("// ADAPTER", definition(source, "bool StorageManager_enqueueRawAdc(") + "\n" + definition(source, "static bool popBdqV2PrimaryRecord_("))
    with tempfile.TemporaryDirectory(prefix="bodaqs-raw-queue-") as tmp:
        cpp, exe = Path(tmp) / "queue.cpp", Path(tmp) / "queue.exe"
        cpp.write_text(fixture, encoding="utf-8")
        subprocess.run([args.compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                        "-DBODAQS_PRODUCTION_RECORDING=1", "-DBODAQS_ADC_RAW_RECORDING_BENCH=1",
                        "-I", str(root / "src"), str(cpp), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True, timeout=15)


if __name__ == "__main__":
    main()
