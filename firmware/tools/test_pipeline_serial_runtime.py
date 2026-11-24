"""Exercise the actual trace export call through production DebugLog serial output."""
import argparse
from pathlib import Path
import subprocess
import tempfile
from analyze_pipeline_trace import analyze


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--compiler",default="g++")
    p.add_argument("--formatted-writer",action="store_true",help="Negative proof of old 256-byte formatter truncation")
    args=p.parse_args()
    root=Path(__file__).resolve().parents[1]
    hook=next(line.strip() for line in (root/"src/RemoteImuRecording.cpp").read_text(encoding="utf-8").splitlines()
              if "MeasurementPipelineTrace::dump(" in line)
    if args.formatted_writer:
        hook=hook.replace('Log_taggedPrintln(LOG_WARN,"PIPE",line)', 'LOGW_TAG("PIPE","%s",line)')
    with tempfile.TemporaryDirectory(prefix="bodaqs-pipeline-serial-") as tmp:
        tmp=Path(tmp)
        (tmp/"Arduino.h").write_text('''#pragma once
#include <stdint.h>
#include <string>
struct FakeSerial {
 std::string output;
 void print(char c) {output+=c;}
 void print(const char* s) {output+=s;}
 void println(const char* s) {output+=s;output+='\\n';}
};
extern FakeSerial Serial;
''',encoding="utf-8")
        fixture='''#include "DebugLog.h"
#include "MeasurementPipelineTrace.h"
#include <cstdio>
FakeSerial Serial;
int main() {
 MeasurementPipelineTrace::reset(9,0);MeasurementPipelineTrace::setParticipants(3);
 BodaqsMeasurementSlot request={};request.context=9;
 MeasurementPipelineTrace::record(request,nullptr,1,1,0,0,0,0,1,true);
 MeasurementPipelineTrace::finish();
 // HOOK
 std::fputs(Serial.output.c_str(),stdout);
}
'''.replace('// HOOK',hook)
        cpp,exe=tmp/"fixture.cpp",tmp/"fixture.exe"
        cpp.write_text(fixture,encoding="utf-8")
        subprocess.run([args.compiler,"-std=c++17","-O2","-Wall","-Wextra","-Werror",
            "-DBODAQS_SPI_MEASUREMENT_V2=1","-DBODAQS_IMU_FLOW_DIAGNOSTICS=1","-DBODAQS_PIPELINE_TRACE=1",
            "-I",str(tmp),"-I",str(root/"src"),str(cpp),str(root/"src/DebugLog.cpp"),"-o",str(exe)],check=True)
        text=subprocess.check_output([str(exe)],text=True)
        result=analyze(text)
        assert result["complete"],result["errors"]
        assert len(max(text.splitlines(),key=len))>255
    print("Actual trace hook / production DebugLog preserves complete long JSON lines: PASS")


if __name__=="__main__":
    main()
