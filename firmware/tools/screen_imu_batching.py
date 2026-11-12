"""Screen real master batch/ACK behavior and host-only profiling overhead."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output exists; preserve prior evidence")
    root = Path(__file__).resolve().parents[1]
    common = root / "can-fd/common/protocol"
    source = (common / "bodaqs_master_service.c").read_text(encoding="utf-8")
    markers = ("(uint32_t)(r->received_ms-b->started_ms)>=20", "(uint32_t)(now-b->started_ms)>=20")
    if any(source.count(marker) != 1 for marker in markers):
        raise ValueError("batch deadline seam changed; inspect before screening")
    results = []
    with tempfile.TemporaryDirectory(prefix="bodaqs-batch-screen-") as temp:
        for deadline, profiling in ((20, 0), (0, 0), (40, 0), (20, 1)):
            text = source
            for marker in markers:
                text = text.replace(marker, "((void)now,true)" if deadline == 0 else marker[:-2] + str(deadline))
            candidate = Path(temp)/f"service-{deadline}-{profiling}.cpp"
            candidate.write_text(text, encoding="utf-8")
            exe = candidate.with_suffix(".exe")
            subprocess.run([args.compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror",
                "-DBODAQS_SPI_MEASUREMENT_V2=1", f"-DBODAQS_MASTER_PHASE_TIMING={profiling}",
                "-I", str(common), str(root/"test/imu_batch_screen.cpp"), str(candidate),
                *[str(common/name) for name in ("bodaqs_master_protocol.c", "bodaqs_control.c", "bodaqs_control_exchange.c")],
                "-o", str(exe)], check=True)
            for delay in (0, 4):
                result = json.loads(subprocess.check_output([str(exe), str(delay)], text=True, timeout=30))
                results.append(dict(deadline_ms=deadline, ack_delay_requests=delay,
                                    profiling=profiling, **result))
    reference = {(r["ack_delay_requests"]): r for r in results if r["deadline_ms"] == 20 and not r["profiling"]}
    for result in results:
        if result["profiling"]:
            for key in ("offered_packets", "admitted_packets", "objects", "ingress_dropped", "empty", "replays"):
                if result[key] != reference[result["ack_delay_requests"]][key]:
                    raise AssertionError("profiling changed simulated behavior: " + key)
    report = {"schema": "bodaqs.imu_batch_screen.v1", "qualification": "host screening only",
        "model": "2 s; two staggered 5-reading packets/1500 us; direct master transfers every500 us; simple alternating reader; no DMA/RTOS/SD/arbitration or production logger scheduler",
        "profiling_timing": "host roundtrip includes client encode/decode; not MCU phase cost or measured device instrumentation tax",
        "temporary_mutations": "batch deadline 0/40 ms in temporary copies only; no deployable batch change",
        "results": results}
    args.output.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
