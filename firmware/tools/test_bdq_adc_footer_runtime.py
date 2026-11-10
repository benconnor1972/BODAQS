"""Exercise the actual multistream footer ADC adapter and independent JSON parse."""
import argparse
from pathlib import Path
import subprocess
import tempfile
from runtime_test_helpers import definition

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler",default="g++")
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    storage=(root/"src/StorageManager.cpp").read_text(encoding="utf-8")
    append=definition(storage,"static void appendBdqV2AdcTiming_(")
    append+="\n"+definition(storage,"static void appendBdqV2MeasurementFailures_(")
    footer=definition(storage,"static String buildBdqV2FinalSummary_(")
    assert "appendBdqV2AdcTiming_(document, endInfo);" in footer, "ADC adapter disconnected from final footer"
    assert "appendBdqV2MeasurementFailures_(document);" in footer
    finalize=definition(storage,"static __attribute__((noinline)) void finalizeBdqV2_(")
    assert "endInfo.externalAdcTiming = AnalogInputManager::stoppedTimingStats();" in finalize
    fixture=(root/"test/bdq_adc_footer_fixture.cpp").read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="bodaqs-adc-footer-") as d:
        temp=Path(d);cpp=temp/"fixture.cpp";exe=temp/"fixture.exe"
        (temp/"FS.h").write_text("#pragma once\nclass File;\n",encoding="utf-8")
        cpp.write_text(fixture.replace("// PRODUCTION_APPEND",append),encoding="utf-8")
        subprocess.run([args.compiler,"-std=c++17","-Wall","-Wextra","-Werror",
            "-I",str(temp),"-I",str(root/"test/stubs"),"-I",str(root/"src"),
            "-I",str(root/".pio/libdeps/bodaqs_s3_mini_n4r2/ArduinoJson/src"),
            str(cpp),"-o",str(exe)],check=True)
        subprocess.run([str(exe)],check=True)
if __name__=="__main__": main()
