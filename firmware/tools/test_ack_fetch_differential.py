"""Compare all wire bytes and master service state against a saved pre-change source."""
import argparse
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    parser.add_argument("--reference-source", type=Path, required=True)
    parser.add_argument("--candidate-source", type=Path,
                        help="Override only for sensitivity checking the comparison")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    common = root / "can-fd/common/protocol"
    with tempfile.TemporaryDirectory(prefix="bodaqs-ack-diff-") as temp:
        temp = Path(temp)
        traces = []
        for name, source in (("reference", args.reference_source),
                             ("candidate", args.candidate_source or common / "bodaqs_master_service.c")):
            exe, trace = temp / f"{name}.exe", temp / f"{name}.trace"
            subprocess.run([args.compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror",
                            "-DBODAQS_SPI_MEASUREMENT_V2=1", "-I", str(common),
                            str(root / "test/ack_fetch_differential_fixture.cpp"), str(source),
                            *[str(common / n) for n in ("bodaqs_master_protocol.c", "bodaqs_control.c", "bodaqs_control_exchange.c")],
                            "-o", str(exe)], check=True)
            subprocess.run([str(exe), str(trace)], check=True)
            traces.append(trace)
        offset = 0
        with traces[0].open("rb") as reference, traces[1].open("rb") as candidate:
            while True:
                expected, actual = reference.read(65536), candidate.read(65536)
                if expected != actual:
                    raise AssertionError(f"wire/state trace differs at or after byte {offset}")
                if not expected:
                    break
                offset += len(expected)
        print(f"ACK-fetch differential wire/result/full-state equivalence: PASS ({offset} bytes)")


if __name__ == "__main__":
    main()
