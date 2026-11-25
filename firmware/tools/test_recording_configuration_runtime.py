"""Serialize the production recording snapshot against independent sensor/config models."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

from runtime_test_helpers import definition


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = (root / "src/BdqLogWriter.cpp").read_text(encoding="utf-8")
    fixture = (root / "test/recording_configuration_runtime_fixture.cpp").read_text(encoding="utf-8")
    fixture = fixture.replace("// PRODUCTION_JSON", "\n".join(definition(source, sig) for sig in (
        "void appendJsonEscaped_(", "void appendKey_(", "void appendKeyString_(",
        "void appendKeyUInt_(", "void appendKeyInt_(", "void appendKeyFloat_(", "void appendKeyBool_(",
        "void appendRecordingConfiguration_(",
    )))
    with tempfile.TemporaryDirectory(prefix="bodaqs-recording-config-") as tmp:
        cpp, exe = Path(tmp) / "snapshot.cpp", Path(tmp) / "snapshot.exe"
        cpp.write_text(fixture, encoding="utf-8")
        subprocess.run([args.compiler, "-std=c++17", "-Wall", "-Wextra", "-DBODAQS_PRODUCTION_RECORDING=1", "-I", str(root / "test/stubs"),
                        "-I", str(root / "src"), str(cpp), str(root / "src/SensorParams.cpp"), "-o", str(exe)], check=True)
        document = json.loads(subprocess.check_output([str(exe)], text=True))
        string_document=json.loads(subprocess.check_output([str(exe),'string'],text=True))
    snapshot = document["recording_configuration"]
    assert snapshot["schema"] == "bodaqs.recording_configuration.v1"
    assert snapshot["local_row_rate_hz"] == 1000
    sensor = snapshot["sensors"][0]
    assert sensor["sensor_id"] == 'pot"one'
    assert sensor["parameters"]["note"] == 'contains "quotes" and \\slashes'
    assert sensor["raw_fields"] == ["pot_raw"]
    assert sensor["assignment"]["kind"] == "external_adc"
    assert sensor["assignment"]["bus"] == 1 and sensor["assignment"]["input"] == 2
    assert sensor["count_domain"] == {"id": "adc_u12_clamped_v1", "minimum": 0, "maximum": 4095}
    assert sensor["calibration"]["available"] is True
    assert sensor["calibration"]["sensor_full_travel"] == 100
    assert sensor["calibration"]["capture_epoch_ms"] == 123456789
    assert sensor["calibration"]["captured_anchors"]["r0_raw"] is None
    assert snapshot["sensors"][1]["calibration"]["available"] is False
    string=string_document['recording_configuration']['sensors'][0]
    assert string['stream_key']=='pot"one_counts'
    assert string['raw_fields']==['wrapped_count','unwrapped_count']
    assert string['count_domain']['id']=='string_pot_counts_v1'
    assert string['calibration']['model']=='string_pot_geometry_v1' and string['calibration']['available']
    print("Embedded recording snapshot: identity, assignment, count domain, calibration and escaping passed")


if __name__ == "__main__":
    main()
