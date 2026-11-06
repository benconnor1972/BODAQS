"""Check the actual linked master's GPIO interrupt vector using TI readelf."""
import argparse
from pathlib import Path
import re
import struct
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--readelf", required=True)
    args = parser.parse_args()

    def readelf(*options):
        return subprocess.check_output(
            [args.readelf, *options, str(args.image)], text=True)

    symbols = {}
    for line in readelf("-s").splitlines():
        fields = line.split()
        if len(fields) == 8 and fields[0].rstrip(":").isdigit():
            symbols[fields[7]] = (int(fields[1], 16), fields[4])
    handler, binding = symbols["GROUP1_IRQHandler"]
    default, _ = symbols["Default_Handler"]
    assert binding == "GLOBAL" and handler != default, (
        "GPIO IRQ still resolves to the weak Default_Handler: "
        f"GROUP1_IRQHandler=0x{handler:08x}, Default_Handler=0x{default:08x}")

    vector_bytes = bytearray()
    for line in readelf("-x", ".intvecs").splitlines():
        if re.match(r"^0x[0-9a-fA-F]+\s", line):
            for word in line.split()[1:5]:
                if re.fullmatch(r"[0-9a-fA-F]{8}", word):
                    vector_bytes.extend(bytes.fromhex(word))
    # MSPM0G3518 GPIOA IRQ 1 is architectural exception 17.
    vector = struct.unpack_from("<I", vector_bytes, 17 * 4)[0]
    assert vector == handler and vector & 1, (
        f"GPIO vector 0x{vector:08x} does not select handler 0x{handler:08x}")
    print(f"PASS: GPIO exception 17 selects GROUP1_IRQHandler at 0x{handler:08x}")


if __name__ == "__main__":
    main()
