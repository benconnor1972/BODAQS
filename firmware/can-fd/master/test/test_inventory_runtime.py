"""Exercise the real status publisher with real inventory mutations/control lanes."""
import argparse
import ctypes
import os
from pathlib import Path
import re
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", required=True)
    args = parser.parse_args()
    if os.name == "nt":
        ctypes.windll.kernel32.SetErrorMode(2)
    root = Path(__file__).resolve().parents[4]
    source = (root / "firmware/can-fd/master/src/main.c").read_text(encoding="utf-8")
    match = re.search(r"static void update_service_status\(void\)\s*\{", source)
    assert match
    end, depth = match.end(), 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    function = source[match.start():end]
    # Observe publication count while retaining the real library implementation.
    assert function.count("bodaqs_master_service_set_inventory(") == 1
    function = function.replace("bodaqs_master_service_set_inventory(", "publish_inventory(")
    start = source.index("typedef struct {")
    end = source.index("} MasterRuntimeInfo;") + len("} MasterRuntimeInfo;")
    fixture = Path(__file__).with_name("inventory_fixture.c").read_text(encoding="utf-8")
    fixture = fixture.replace("/* RUNTIME_TYPE */", source[start:end]).replace("/* PRODUCTION_STATUS */", function)
    protocol = root / "firmware/can-fd/common/protocol"
    network = root / "firmware/can-fd/common/network"
    sources = [protocol / name for name in ("bodaqs_master_service.c", "bodaqs_master_protocol.c",
                                            "bodaqs_control.c", "bodaqs_control_exchange.c")]
    with tempfile.TemporaryDirectory(prefix="bodaqs-inventory-") as temp:
        c, exe = Path(temp) / "inventory.c", Path(temp) / "inventory.exe"
        c.write_text(fixture, encoding="utf-8")
        subprocess.run([args.cc, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-ffunction-sections",
                        "-Wl,--gc-sections", "-I"+str(protocol), "-I"+str(network),
                        "-I"+str(root / "firmware/can-fd/common/transport"), str(c),
                        *map(str, sources), str(network / "bodaqs_node_inventory.c"), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
