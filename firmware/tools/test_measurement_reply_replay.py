"""Independent byte construction versus the real decoder/replay adapter."""
import argparse
import zlib
from replay_measurement_replies import replay


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default="g++")
    args = parser.parse_args()
    valid = bytearray(256); valid[:4] = b"BM\x02\x00"
    def crc(raw):
        raw[252:] = zlib.crc32(raw[:252]).to_bytes(4,"little")
        return raw
    crc(valid)
    bad_crc = valid.copy();bad_crc[100] = 0x1a # Binary stdin must preserve this byte.
    reserved = valid.copy();reserved[239] = 1;crc(reserved)
    padding = valid.copy();padding[60] = 1;crc(padding)
    summary = {"remote_measurement_failures": {"available": True,"decode_failed_slots": 100,
        "rejected_replies": {"available": True,"capacity": 4,"captured": 4,
            "selection": "first_decode_failures_while_confirmed",
            "entries": [{"slot": i+1,"request_kind":14,"reply_hex": raw.hex()}
                        for i,raw in enumerate([bytearray(256),bad_crc,reserved,padding])]}}}
    report = replay(summary,args.compiler)
    assert [r["category"] for r in report["entries"]] == ["framing","crc_mismatch","protocol_fields","protocol_fields"]
    assert not any(r["canonical_decoder_accepts"] for r in report["entries"])
    assert report["entries"][0]["all_zero"]
    capture = summary["remote_measurement_failures"]["rejected_replies"]
    capture["entries"] = [{"slot":5,"request_kind":1,"reply_hex":valid.hex()}];capture["captured"] = 1
    assert replay(summary,args.compiler)["entries"][0]["canonical_decoder_accepts"]
    capture["available"] = False
    assert not replay(summary,args.compiler)["available"]
    print("Actual v2 decoder replay: framing, CRC, CRC-valid reserved/padding and valid slot PASS")


if __name__ == "__main__":
    main()
