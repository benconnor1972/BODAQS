"""Replay bounded rejected replies from a finalized BDQ or final-summary JSON.

The acceptance verdict comes from the production v2 C decoder. Independent CRC
and header observations classify failures; they never replace its verdict.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zlib

ROOT = Path(__file__).resolve().parents[2]


def replay(summary, compiler="g++"):
    failures = summary.get("remote_measurement_failures", {})
    capture = failures.get("rejected_replies", {})
    if not failures.get("available") or not capture.get("available"):
        return {"available": False, "reason": "No retired matching-context capture"}
    entries = capture["entries"]
    if capture["capacity"] != 4 or capture["captured"] != len(entries) or len(entries) > 4:
        raise ValueError("Invalid bounded capture counts")
    protocol = ROOT / "firmware/can-fd/common/protocol"
    header = protocol / "bodaqs_measurement.h"
    result = {"available": True, "selection": capture["selection"],
              "decode_failed_slots": failures["decode_failed_slots"],
              "decoder_header_sha256": hashlib.sha256(header.read_bytes()).hexdigest(),
              "entries": []}
    source = r'''
#include "bodaqs_measurement.h"
#include <cstdio>
int main() {
  uint8_t bytes[256]; BodaqsMeasurementSlot slot={};
  if(std::fread(bytes,1,sizeof bytes,stdin)!=sizeof bytes || std::fgetc(stdin)!=EOF) return 2;
  std::printf("%u\n",bodaqs_measurement_decode(bytes,sizeof bytes,&slot)?1:0);
}
'''
    # On Windows stdin must be binary: 0x1a and CR/LF are valid captured bytes.
    if sys.platform == "win32":
        source = source.replace('#include <cstdio>', '#include <cstdio>\n#include <io.h>\n#include <fcntl.h>')
        source = source.replace('uint8_t bytes[256];', '_setmode(_fileno(stdin),_O_BINARY);\n  uint8_t bytes[256];')
    with tempfile.TemporaryDirectory(prefix="bodaqs-reply-replay-") as directory:
        cpp, exe = Path(directory)/"replay.cpp", Path(directory)/"replay.exe"
        cpp.write_text(source, encoding="utf-8")
        subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                        "-DBODAQS_SPI_MEASUREMENT_V2=1", "-I", str(protocol), str(cpp), "-o", str(exe)], check=True)
        for entry in entries:
            text = entry["reply_hex"]
            if len(text) != 512:
                raise ValueError("Captured reply must contain exactly 256 bytes")
            raw = bytes.fromhex(text)
            if len(raw) != 256:
                raise ValueError("Captured reply must contain exactly 256 bytes")
            accepted = subprocess.check_output([str(exe)], input=raw).strip() == b"1"
            crc = zlib.crc32(raw[:252]) & 0xffffffff
            received_crc = int.from_bytes(raw[252:], "little")
            header_ok = raw[:3] == b"BM\x02" and raw[3] <= 14
            category = ("accepted" if accepted else "framing" if not header_ok else
                        "crc_mismatch" if crc != received_crc else "protocol_fields")
            result["entries"].append({"slot": entry["slot"], "request_kind": entry["request_kind"],
                "reported_decode_reason":entry.get("decode_reason"),"bus":entry.get("bus"),
                "canonical_decoder_accepts": accepted, "category": category,
                "magic_hex": raw[:2].hex(), "version": raw[2], "kind": raw[3],
                "crc_matches": crc == received_crc, "computed_crc": f"{crc:08x}",
                "received_crc": f"{received_crc:08x}", "all_zero": not any(raw),
                "all_ff": all(b == 255 for b in raw),
                "v2_header_offsets": [i for i in range(254) if raw[i:i+3] == b"BM\x02"]})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Finalized .bdq or extracted final-summary JSON")
    parser.add_argument("--compiler", default="g++")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.input.suffix.lower() == ".bdq":
        sys.path.insert(0, str(ROOT/"analysis"))
        from bodaqs_analysis.io_bdq import read_bdq
        recording = read_bdq(args.input)
        if recording.detected_errors or not recording.final_summary:
            raise ValueError("BDQ must have an intact final summary")
        summary = recording.final_summary
    else:
        summary = json.loads(args.input.read_text(encoding="utf-8"))
    report = replay(summary, args.compiler)
    text = json.dumps(report, indent=2)+"\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
