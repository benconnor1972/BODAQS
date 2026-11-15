"""Exercise the real idle-turn selector against real four-window transport state.

Regression for selecting the expected window head, not obsolete ring slot0.
No firmware source is edited. Production definitions are extracted verbatim.
"""
import json
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--compiler',default='g++')
args=parser.parse_args()
SOURCE=Path(__file__).resolve().parents[2]
evidence=tempfile.TemporaryDirectory(prefix='bodaqs-selector-evidence-')
ROOT=Path(evidence.name)
sys.path.insert(0,str(SOURCE/'firmware/tools'))
from runtime_test_helpers import definition
acq=(SOURCE/'firmware/src/AcquisitionControl.cpp').read_text(encoding='utf-8')
manager=(SOURCE/'firmware/src/CanMasterManager.cpp').read_text(encoding='utf-8')
cpp='''#include "CanMasterManager.h"
#include <cassert>
#include <cstdio>
using namespace CanMasterManager;
static MeasurementTransport transport;
static uint8_t dataMask=15,dataCursor=0;
'''+definition(acq,'static bool due(')+'\n'+definition(acq,'static bool chooseIdleTurnData(')+'\n'+definition(manager,'static void sampleCredits_(')+r'''
int main() {
  // Base2 belongs to ring slot1. Slot0 already holds later unit5, which must
  // wait for its predecessors before downstream acceptance. Evidence polls
  // are cooling down; all sample windows still advertise open positions.
  for(unsigned n=0;n<4;++n) {
    transport.sampleNext[n]=2;
    transport.nextHeadPollMs[1][n]=1100;
    auto& later=sampleWindowInbox(transport,n,0);
    later.state.object=5;later.state.complete=1;later.admitted=false;
  }
  transport.sampleNodes=15;
  uint8_t credits[32]={};sampleCredits_(transport,credits);
  for(unsigned n=0;n<4;++n) {
    assert(bodaqs_measurement_get(credits+8*n,4)==2);
    assert(credits[8*n+4]==8); // base2,3,4 open; later5 already held.
  }
  uint8_t cls=3,node=0;
  bool chosen=chooseIdleTurnData(100,cls,node);
  assert(chosen && cls==1);
  printf("future_slot0: open window credits exist on all four nodes; selected=%u class=%u\n",chosen,cls);
  // With evidence eligible, sample work in the expected window still wins.
  for(unsigned n=0;n<4;++n)transport.nextHeadPollMs[1][n]=0;
  chosen=chooseIdleTurnData(100,cls,node);
  assert(chosen && cls==1);
  printf("future_slot0_evidence_ready: selected class=%u node=%u\n",cls,node);
  // Same windows/credits, but slot0 now admitted: changing the obsolete slot0
  // admission cannot change whether a sample-window request is possible.
  for(unsigned n=0;n<4;++n) {
    sampleWindowInbox(transport,n,0).admitted=true;
    transport.nextHeadPollMs[1][n]=1100;
  }
  chosen=chooseIdleTurnData(100,cls,node);
  assert(chosen && cls==1);
  printf("slot0_admitted: selected class=%u node=%u\n",cls,node);
}
'''
env=dict(os.environ)
with tempfile.TemporaryDirectory(prefix='bodaqs-r30-selector-') as folder:
    folder=Path(folder);(ROOT/'selector.cpp').write_text(cpp,encoding='utf-8')
    command=[args.compiler,'-std=c++17','-DBODAQS_SPI_MEASUREMENT_V4=1','-DBODAQS_SPI_BULK_BYTES=512',
             '-I',str(SOURCE/'firmware/test/stubs'),'-I',str(SOURCE/'firmware/src'),
             str(ROOT/'selector.cpp'),'-o',str(folder/'probe.exe')]
    build=subprocess.run(command,capture_output=True,env=env)
    (ROOT/'selector-build.log').write_bytes(build.stdout+build.stderr)
    assert build.returncode==0,build.stderr.decode(errors='replace')
    run=subprocess.run([str(folder/'probe.exe')],capture_output=True,env=env)
    (ROOT/'selector-result.txt').write_bytes(run.stdout+run.stderr)
    assert run.returncode==0,run.stderr.decode(errors='replace')
    (ROOT/'selector-command.json').write_text(json.dumps(command,indent=2)+'\n',encoding='utf-8')
    print(run.stdout.decode())
