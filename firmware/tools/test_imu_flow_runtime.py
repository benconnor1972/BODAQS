"""Check diagnostic scope and correlated retirement timing without device access."""
import argparse
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="bodaqs-imu-flow-") as temp:
        cpp, exe = Path(temp)/"fixture.cpp", Path(temp)/"fixture.exe"
        cpp.write_text('''#include "ImuFlowDiagnostics.h"
#include <cassert>
#include <cstdio>
int main() {
 using namespace ImuFlowDiagnostics;
 reset(123,100);
 request(14,1,0,7,0xfffffff0u,2);
 request(14,1,0,7,0xfffffff8u,2); // retry must not restart wait
 proof(1,1,7,0x10u);proof(1,0,8,0x10u); // wrong node/object cannot complete it
 assert(live.proofMatches[0]==0);
 loss(3,200,0x10u);
 assert(firstLoss.context==123 && firstLoss.proofPending[0]==1);
 assert(firstLoss.proofOldestUs[0]==32);
 proof(1,0,7,0x20u);
 assert(live.proofMatches[0]==1 && live.proofWaitTotalUs[0]==48 && live.proofWaitMaxUs[0]==48);
 proof(1,0,7,0x30u);assert(live.proofMatches[0]==1); // replay after consumption
 consumer(1,false,2048,12,2048,512);
 fragment(1,true);fragment(1,false);admitted(1);
 loss(8,300,0x40u);
 assert(firstLoss.lossCounter==3 && firstLoss.observedMs==200 && firstLoss.sampleQueuePeak==0);
 finish(400,0x50u);
 assert(!active && haveFinished && finished.sampleQueuePeak==2048 && finished.consumerWait[0]==1);
 assert(finished.proofPending[0]==0 && finished.fetchTargets[1]==2);
 request(1,1,0,0,100);consumer(1,true,1,1,2048,512);finish(500,110);
 assert(finished.observedMs==400 && live.requests[0]==0); // frozen scope is immutable
 reset(456,600);
 assert(live.context==456 && !haveFirstLoss && !haveFinished && live.proofMatches[0]==0);
 puts("flow snapshots: correlated proof/retry/wrap, first-loss freeze, final freeze/reset PASS");
}
''')
        subprocess.run([args.compiler,"-std=c++17","-Wall","-Wextra","-Werror",
                        "-DBODAQS_IMU_FLOW_DIAGNOSTICS=1","-I",str(root/"src"),str(cpp),"-o",str(exe)],check=True)
        subprocess.run([str(exe)],check=True)


if __name__ == "__main__":
    main()
