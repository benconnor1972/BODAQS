import copy
import struct
import zlib

import pytest

from bodaqs_analysis.spi_boundary_trace import HEADER, correlate, parse_trace, exact64


def wire(context=0x1122334455667788):
    data=bytearray(256)
    data[:4]=b"BM\x02\x00"
    struct.pack_into("<Q",data,4,context)
    data[16]=255
    struct.pack_into("<I",data,252,zlib.crc32(data[:252]))
    return bytes(data)


def fixture():
    # Independent fixed-layout fixture, not a call to the trace encoder/parser.
    context=0x1122334455667788;boot=0xaabbccddeeff0011
    request=wire();received=b"\0"+request[1:]
    fields=dict(version=1,bytes=7328,capacity=8,count=1,next=1,ordinal=2,
                frozen=1,overflow=0,boot_low=boot&0xffffffff,boot_high=boot>>32,
                context_low=context&0xffffffff,context_high=context>>32,
                marker_ordinal=2,nonce=42,failed_device_sequence=100,logger_slot=42,
                request_crc=int.from_bytes(request[252:],"little"),reply_crc=int.from_bytes(received[252:],"little"),
                arm_max_us=9,end_max_us=12,source_address=0x20210000)
    raw=bytearray(7328);struct.pack_into("<21I",raw,0,*(fields[k] for k in HEADER))
    struct.pack_into("<3I",raw,384,1,256,0x20210000)
    raw[484:740]=request;raw[740:996]=request;raw[996:1252]=request
    entry={"slot":42,"request_available":True,"request_hex":request.hex(),"reply_hex":received.hex(),
           "bus":{"available":True,"cs":40,"device_sequence":100,"device_sequence_valid":True}}
    summary={"remote_measurement_failures":{"available":True,"rejected_replies":{"available":True,"entries":[entry],
             "boundary_trace":{"attempted":True,"transferred":True,"adjacent":True,"nonce":42,
                               "failed_device_sequence":100,"marker_device_sequence":101}}}}
    return raw,summary,{"master_boot":str(boot),"measurement_context":str(context)}


def test_literal_same_exchange_zero_byte_and_source_controls():
    raw,summary,source=fixture()
    result=correlate(raw,summary,source)
    assert result["classification"]=="zero_first_byte_after_header_crc_valid_staging"
    assert result["received_diff_offsets"]==[0]
    assert not result["first_clock_readiness_proven"]
    assert not result["physical_wire_or_logger_receive_location_proven"]
    raw[740+7]^=1
    assert correlate(raw,summary,source)["classification"]=="selected_source_changed"
    raw[484+7]^=1
    assert correlate(raw,summary,source)["classification"]=="source_header_or_crc_invalid_at_arm"


@pytest.mark.parametrize("change",["truncated","unfrozen","overflow","gap","short","request","context","boot",
                                  "nonce","fingerprint","nonadjacent","saturated","duplicate","hexspace"])
def test_inconclusive_mismatch_and_ambiguity(change):
    raw,summary,source=fixture();capture=summary["remote_measurement_failures"]["rejected_replies"]
    if change=="truncated":raw=raw[:-1]
    elif change=="unfrozen":struct.pack_into("<I",raw,24,0)
    elif change=="overflow":struct.pack_into("<I",raw,28,1)
    elif change=="gap":struct.pack_into("<I",raw,384,4)
    elif change=="short":struct.pack_into("<I",raw,388,84)
    elif change=="request":raw[996+50]^=1 # Same fingerprint is insufficient.
    elif change=="context":source["measurement_context"]="12"
    elif change=="boot":source["master_boot"]="12"
    elif change=="nonce":capture["boundary_trace"]["nonce"]=43
    elif change=="fingerprint":struct.pack_into("<I",raw,68,1)
    elif change=="nonadjacent":capture["boundary_trace"]["marker_device_sequence"]=102
    elif change=="saturated":capture["entries"][0]["bus"]["device_sequence"]=2**32-1
    elif change=="duplicate":capture["entries"].append(copy.deepcopy(capture["entries"][0]))
    elif change=="hexspace":capture["entries"][0]["reply_hex"]="  "+capture["entries"][0]["reply_hex"][2:]
    with pytest.raises(ValueError):correlate(raw,summary,source)


def test_ring_wrap_and_identity_precision():
    raw,_,_=fixture()
    for key,value in (("count",8),("next",3),("ordinal",20),("marker_ordinal",20)):
        struct.pack_into("<I",raw,HEADER.index(key)*4,value)
    for n in range(8):struct.pack_into("<3I",raw,384+868*((3-8+n)%8),12+n,256,0x20210000)
    assert [e["ordinal"] for e in parse_trace(raw)["entries"]]==list(range(12,20))
    assert exact64("18446744073709551615")==2**64-1
    for value in (2**53,True,1.5,"-1","18446744073709551616"):
        with pytest.raises(ValueError):exact64(value)
