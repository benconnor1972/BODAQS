"""Extract selected A8 pin/mode facts from the real board table, without a device."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile


def collect(compiler:str) -> dict:
    root=Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="bodaqs-board-contract-") as directory:
        source=Path(directory)/"contract.cpp";exe=Path(directory)/"contract.exe"
        source.write_text('''#include "BoardProfile.h"
#include <cstdio>
int main() {
 const auto& p=board::GetBoardProfile(board::BoardID::BODAQS_A8);
 std::printf("{\\"pins\\":{\\"sck\\":%d,\\"miso\\":%d,\\"mosi\\":%d,\\"master_cs\\":%d,\\"adc_cs\\":[%d,%d]},\\"spi_mode\\":%u,\\"legacy_master_hz\\":%u,\\"adc_hz\\":[%u,%u]}",
 p.spi.sck,p.spi.miso,p.spi.mosi,p.can_fd_master.cs_pin,p.external_adcs[0].cs_pin,p.external_adcs[1].cs_pin,
 unsigned(p.can_fd_master.spi_mode),unsigned(p.can_fd_master.spi_hz),unsigned(p.external_adcs[0].spi_hz),unsigned(p.external_adcs[1].spi_hz));
}
''',encoding="utf-8")
        subprocess.run([compiler,"-std=gnu++2a","-I",str(root/"test/stubs"),"-I",str(root/"src"),str(source),str(root/"src/BoardProfile.cpp"),"-o",str(exe)],check=True)
        result=json.loads(subprocess.check_output([str(exe)]))
    files=("src/CanMasterManager.cpp","src/SharedSpiBus.cpp","src/AnalogInputManager.cpp")
    result["buffer_and_transfer_declarations"]={}
    for name in files:
        path=root/name
        if path.exists():result["buffer_and_transfer_declarations"][name]=[
            {"line":i,"source":line.strip()} for i,line in enumerate(path.read_text(encoding="utf-8").splitlines(),1)
            if re.search(r"uint8_t .*\b(?:tx|rx|command|setup|cmd)\[|transferBytes\(",line)]
    result["basis"]="compiled_A8_board_table_and_literal_source_declarations_not_physical_observation"
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--compiler",default="g++")
    parser.add_argument("--output",type=Path,required=True);args=parser.parse_args()
    args.output.write_text(json.dumps(collect(args.compiler),indent=2)+"\n",encoding="utf-8")
