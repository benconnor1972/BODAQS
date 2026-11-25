"""Bridge actual firmware membership/status JSON into the normal BDQ importer.

The BDQ envelope and single native row are encoded independently of firmware and
reader helpers. No native data or stream descriptor exists for the absent IMU.
"""
import argparse
import binascii
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

from runtime_test_helpers import definition


def compile_fixture(args, firmware, library, directory, name, fixture):
    cpp, exe = directory / (name + ".cpp"), directory / (name + ".exe")
    cpp.write_text(fixture, encoding="utf-8")
    subprocess.run([args.compiler, "-std=c++17", "-Wall", "-Wextra",
                    "-DBODAQS_PRODUCTION_RECORDING=1", "-I", str(library),
                    "-I", str(firmware / "test/stubs"), "-I", str(firmware / "src"),
                    str(cpp), "-o", str(exe)], check=True)
    return subprocess.check_output([str(exe)], text=True)


def recording_bytes(metadata, footer):
    def chunk(kind, sequence, payload):
        if isinstance(payload, dict):
            payload = json.dumps(payload, separators=(",", ":")).encode()
        return struct.pack("<4sHHIII", b"BDQC", 1, kind, sequence, len(payload),
                           binascii.crc32(payload) & 0xffffffff) + payload

    descriptor = {
        "stream_id": 1, "stream_key": "primary", "stream_kind": "regular",
        "sensor_id": None, "source_device_id": "A8_fixture", "transport": "local",
        "clock_id": "logger_monotonic", "record_format": "fixed_mixed_v2",
        "record_size_bytes": 16,
        "timebase": {"type": "native_ticks", "native_tick_field": "native_tick",
                     "native_tick_bits": 32, "native_tick_modulus": 1 << 32,
                     "nominal_tick_period_us": {"numerator": 1, "denominator": 1},
                     "nominal_sample_rate_hz": {"numerator": 1000, "denominator": 1},
                     "expected_sequence_step": 1, "clock_relation": "logger_monotonic"},
        "channels": [
            {"field": field, "quantity": quantity, "unit": unit,
             "storage_type": storage, "byte_offset": offset, "class": category}
            for field, quantity, unit, storage, offset, category in [
                ("sequence", "sample_sequence", "count", "uint32", 0, "diagnostic"),
                ("native_tick", "sensor_time", "tick", "uint32", 4, "diagnostic"),
                ("status_flags", "status", "bitfield", "uint16", 8, "diagnostic"),
                ("travel_raw", "raw", "count", "int16", 12, "signal")]],
        "status_flags": {"discontinuity_before": 1}}
    catalog = {"schema_format": "bdq.stream_catalog.v1", "endianness": "little",
               "record_prefix": {"format": "bdq.stream_record_prefix.v1", "size_bytes": 12},
               "streams": [descriptor]}
    metadata = dict(metadata, format="bdq.v2", recording_id="membership_fixture",
                    format_name="BDQLOG v2", firmware_name="BODAQS", firmware_version="fixture",
                    hardware_version="BODAQS A8", timezone="Australia/Perth", created_unix_us=0,
                    log_format="bodaqs_multi_stream_binary",
                    device_id="A8_fixture", native_stream_contract="bodaqs.native_stream.v1",
                    stream_count=1, logger_monotonic_clock={"clock_id": "logger_monotonic",
                                                           "unit": "us", "nondecreasing": True})
    # Prefix: sequence, tick, status, reserved; payload: one raw count, padding.
    row = struct.pack("<IIHHhH", 0, 1000, 0, 0, 321, 0)
    data = struct.pack("<HHIIIHHI", 1, 1, 0, 0, 1, 16, 0, 0) + row
    chunks = [chunk(1, 0, metadata), chunk(2, 1, catalog), chunk(3, 2, data)]
    if footer is not None:
        chunks.append(chunk(5, 3, footer))
    return struct.pack("<8sHHIQII", b"BDQLOG\x00\x02", 2, 0, 32, 0, 0, 0) + b"".join(chunks)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    parser.add_argument("--arduinojson", type=Path)
    args = parser.parse_args()
    firmware = Path(__file__).resolve().parents[1]
    library = args.arduinojson or firmware / ".pio/libdeps/bodaqs_a8_production/ArduinoJson/src"
    sys.path.insert(0, str(firmware.parent / "analysis"))
    from bodaqs_analysis.pipeline import load_bdq_session
    from bodaqs_analysis.io_bdq import read_bdq

    writer = (firmware / "src/BdqLogWriter.cpp").read_text(encoding="utf-8")
    api = (firmware / "src/Routes_Api.cpp").read_text(encoding="utf-8")
    fixture = (firmware / "test/recording_membership_import_fixture.cpp").read_text(encoding="utf-8")
    fixture = fixture.replace("// PRODUCTION_JSON", "\n".join(definition(writer, sig) for sig in (
        "void appendJsonEscaped_(", "void appendKey_(", "void appendKeyString_(",
        "void appendKeyUInt_(", "void appendKeyBool_(", "void appendRecordingMembership_(")))
    fixture = fixture.replace("// PRODUCTION_API", definition(api, "static void addRecordingReadinessJson_("))

    # Reuse the existing footer's hardware models, but execute the actual bounded
    # serializer after a prepared remote is lost; local travel remains admitted.
    footer_fixture = (firmware / "test/operational_finalization_runtime_fixture.cpp").read_text(encoding="utf-8")
    footer_fixture = footer_fixture.split("// PRODUCTION")[0]
    storage = (firmware / "src/StorageManager.cpp").read_text(encoding="utf-8")
    footer_fixture += storage[storage.index("static size_t buildOperationalSummary_("):
                              storage.index("\n#endif\n\nstatic __attribute__((noinline)) void finalizeBdqV2_")]
    footer_fixture += '''
int main() {
  auto& observation = RecordingReadiness::declared;
  observation.decision.requested=7;
  observation.decision.selected=1;
  observation.decision.excluded=6;
  observation.decision.candidate=true;
  observation.reservation=RecordingAdmission::Reservation::Acquired;
  s_bdqV2DescriptorCount=0;
  const auto bytes=buildOperationalSummary_({});
  assert(bytes);
  std::fwrite(workspace,1,bytes,stdout);
}
'''
    with tempfile.TemporaryDirectory(prefix="bodaqs-membership-import-") as tmp:
        directory = Path(tmp)
        output = compile_fixture(args, firmware, library, directory, "membership", fixture)
        header, end = json.JSONDecoder().raw_decode(output)
        status = json.loads(output[end:])
        footer = json.loads(compile_fixture(args, firmware, library, directory, "footer", footer_fixture))
        idle, running_only, reserved_only, ready = status["cases"]
        assert idle["observation_scope"] == "idle_current"
        assert idle["can_prepare"] and not idle["resources_reserved"] and not idle["acquisition_ready"]
        assert not running_only["resources_reserved"] and not running_only["acquisition_ready"]
        assert reserved_only["resources_reserved"] and not reserved_only["acquisition_ready"]
        assert ready["resources_reserved"] and ready["acquisition_ready"]
        assert ready["observation_scope"] == "frozen_session"
        for observation in status["cases"]:
            assert observation["qualified"] is False and observation["unqualified_candidate"] is True
            assert observation["qualification_profile"] is None and observation["qualification_revision"] == 0

        for final in (None, footer):
            path = directory / ("interrupted.bdq" if final is None else "partial-admission.bdq")
            path.write_bytes(recording_bytes(header, final))
            assert not read_bdq(path).detected_errors
            session = load_bdq_session(path)
            membership = session["meta"]["recording_membership"]
            assert membership["preparation"] == header["recording_membership"]
            assert membership["preparation"]["qualified"] is False
            assert membership["preparation"]["unqualified_candidate"] is True
            travel, lost, absent = membership["sources"]
            assert travel["sensor_id"] == "travel" and travel["selected_at_preparation"]
            assert lost["sensor_id"] == "imu_late_loss" and lost["selected_at_preparation"]
            assert absent["sensor_id"] == 'imu"absent' and absent["sensor_type"] == "lsm6dso32x_imu"
            assert absent["requested"] and not absent["selected_at_preparation"]
            assert absent["exclusion_declared"] and absent["exclusion_reason"] == "unavailable"
            assert not absent["sample_count_inferred"]
            assert 'recording_source_excluded:imu"absent:unavailable' in session["qc"]["warnings"]
            assert len(session["df"]) == 1
            assert session["df"]["travel_raw [count]"].tolist() == [321]
            assert not session["stream_dfs"]  # No invented IMU stream or samples.
            if final is None:
                assert membership["finalization"] is None
                assert travel["selected_at_finalization"] is None
                assert travel["membership_outcome"] == "unknown_without_valid_final_membership"
                assert lost["selected_at_finalization"] is None
                assert lost["membership_outcome"] == "unknown_without_valid_final_membership"
                assert absent["selected_at_finalization"] is None
            else:
                assert membership["finalization"] == footer["recording_membership"]
                assert travel["selected_at_finalization"] is True
                assert lost["selected_at_finalization"] is False
                assert lost["exclusion_reason"] == "not_admitted_at_finalization"
                assert membership["finalization"]["resources_reserved"]
                assert not membership["finalization"]["qualified"]
                assert membership["finalization"]["unqualified_candidate"]
    print("Recording contract: actual header/API/footer JSON -> normal BDQ import; absent identity, unknown tail, final exclusion and honest readiness passed")


if __name__ == "__main__":
    main()
