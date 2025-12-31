# hex_sentinel_check.py
# Run:  python hex_sentinel_check.py mylog.csv
import sys

def check_file(path):
    bad = []
    with open(path, "rb") as f:
        data = f.read()
    for i, b in enumerate(data):
        if b in (9, 10, 13):  # tabs/newlines OK
            continue
        if not (32 <= b <= 126):
            bad.append((i, b))
    if not bad:
        print(f"[OK] {path}: all {len(data):,} bytes are printable ASCII.")
        return
    print(f"[WARN] {path}: found {len(bad)} non-printable bytes.")
    for i, b in bad[:20]:  # show first 20 offenders
        hexview = f"{b:02X}"
        context = data[max(0, i-10):i+10].decode("latin1", errors="replace")
        print(f"  Offset {i:>8}: 0x{hexview}  ({context!r})")
    if len(bad) > 20:
        print(f"  ...and {len(bad)-20} more")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python hex_sentinel_check.py <file>")
        sys.exit(1)
    for path in sys.argv[1:]:
        check_file(path)
