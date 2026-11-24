"""Audit linked production roots and report section sizes; no device claims."""
import argparse
from pathlib import Path
import re
import subprocess


FORBIDDEN = (
    "BdqLogWriter::begin(", "BdqLogWriter::end(", "BdqLogWriter::writeSample(",
    "finalizeCsv_(", "TransformRegistry::", "gTransforms", "bootGate(",
    "ControlPollingDiagnostics::", "RecordingTimelineDiagnostics::", "ZipArchiveWriter_createStoreOnly(",
)
REQUIRED = (
    "BdqV2Writer::begin(", "BdqV2Writer::end(", "BacklogBalance::runOwner(",
    "StorageManager_enqueueRawAdc(", "AnalogInputManager::activateRecordingPlan(",
    "__wrap_sdmmc_write_sectors", "BMI270ImuSensor::", "DANF10NGpsSensor::",
    "AS5600AngleSensor::", "AS5048BAngleSensor::", "StringPotCountStream::",
)


def inspect(path, nm, size):
    symbols = subprocess.check_output([nm, "--defined-only", "--demangle", str(path)], text=True)
    sections = subprocess.check_output([size, "-A", str(path)], text=True)
    sizes = {}
    for line in sections.splitlines():
        fields = line.split()
        if len(fields)>1 and fields[0].startswith(".") and fields[1].isdigit():
            sizes[fields[0]] = int(fields[1])
    metrics = {
        "static_dram_bytes": sum(sizes.get(key,0) for key in (".dram0.data", ".dram0.bss")),
        "loadable_flash_bytes": sum(sizes.get(key,0) for key in (
            ".iram0.vectors", ".iram0.text", ".dram0.data", ".flash.text", ".flash.rodata")),
    }
    return symbols, metrics


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("elf", type=Path)
    parser.add_argument("--nm", default="xtensa-esp32s3-elf-nm")
    parser.add_argument("--size", default="xtensa-esp32s3-elf-size")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--diagnostic", type=Path)
    args=parser.parse_args()
    symbols, metrics = inspect(args.elf,args.nm,args.size)
    for name in FORBIDDEN:
        assert name not in symbols, "obsolete production root: " + name
    assert not re.search(r"ImuFlowDiagnostics::(?:live|finished|firstLoss|waits|active)\b",symbols)
    for name in REQUIRED:
        assert name in symbols, "missing operational root: " + name
    print(str(args.elf) + ": legacy/transform/profiling roots absent; operational paths present")
    print(metrics)
    if args.baseline:
        _, previous = inspect(args.baseline,args.nm,args.size)
        print("baseline", previous)
        print("change", {key:metrics[key]-previous[key] for key in metrics})
    if args.diagnostic:
        retained, _ = inspect(args.diagnostic,args.nm,args.size)
        for name in ("BdqLogWriter::begin(","BdqLogWriter::writeSample(","finalizeCsv_(","gTransforms"):
            assert name in retained, "missing retained diagnostic root: " + name
        print("Diagnostic legacy writers/transform registry retained")


if __name__ == "__main__":
    main()
