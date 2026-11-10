"""Independent file vectors for delivery, prefix and STOP outcome reporting."""
import struct

import pytest

from bodaqs_analysis.first_imu_recording import assess_first_imu_recording
from test_io_bdq_can_imu import _sample_descriptor, _evidence_descriptor
from test_io_bdq_v2 import FILE_HEADER, FILE_MAGIC_V2, _catalog, _metadata, _chunk, _json_chunk, _stream_data


def recording(tmp_path, *, gap=False, footer=True, confirmed=True, discarded=False, torn=False, source_loss=0, capture_loss=0, valid_raw=True, recipe=None):
    sample=_sample_descriptor()
    sample.update(stream_kind="intermittent",record_size_bytes=100)
    sample["acquisition"].update(payload_schema="bodaqs.can_imu_packets.v1", provider_uid="123",
        node_address=0, master_boot="99", recording_id="77", control_session="1", measurement_context="9",
        effective_descriptor_hex="00"*192)
    effective=bytearray(192);effective[0]=3;effective[2]=1;effective[4]=2;effective[5]=3
    struct.pack_into("<6I",effective,48,3333,1,3333,1,32000,2000000)
    sample["acquisition"]["effective_descriptor_hex"]=effective.hex()
    fields=[("source_segment_id",12,"uint32"),("sequence_floor",16,"uint32"),
        ("master_receive_tick",20,"uint32"),("master_receive_ordinal_low",24,"uint32"),
        ("master_receive_ordinal_high",28,"uint32"),("first_sequence_low",32,"uint16"),
        ("stream_epoch",34,"uint8"),("packet_flags",35,"uint8"),("packet_length",36,"uint16"),("reception_flags",38,"uint8")]
    fields += [(f"{axis}{slot}",40+12*slot+2*i,"int16") for slot in range(5) for i,axis in enumerate(("ax","ay","az","gx","gy","gz"))]
    sample["channels"]=sample["channels"][:3]+[{"field":n,"byte_offset":o,"storage_type":t} for n,o,t in fields]
    timing=_evidence_descriptor();timing.update(stream_id=3)
    timing["acquisition"].update(related_sample_stream_id=2)
    rows=[]
    for index,seq in enumerate((0,10 if gap else 5)):
        row=bytearray(100);struct.pack_into("<IIIIIII",row,0,index,100+index,0,1,0,42,index+1)
        struct.pack_into("<HBBH",row,32,seq,1,5,64)
        for slot in range(5):struct.pack_into("<6h",row,40+12*slot,-32768,32767,-1,0,123,-456)
        rows.append(bytes(row))
    last=14 if gap else 9
    observations=[]
    for index,kind,seq in ((0,2,0),(1,0,last),(2,8,last)):
        row=bytearray(224);struct.pack_into("<II",row,0,index,100+index)
        row[12]=1 if kind==0 else 6;row[14]=1
        struct.pack_into("<II",row,20,1,seq);row[200]=kind
        struct.pack_into("<H",row,208,1 if kind else 0)
        if kind==0:
            if valid_raw:
                struct.pack_into("<I",row,16,sum(1 << bit for bit in (0,1,2,4,5,6,21)))
                struct.pack_into("<III",row,28,7,1,1)
                row[201]=0xd8;struct.pack_into("<H",row,204,7)
            struct.pack_into("<I",row,148,source_loss);struct.pack_into("<I",row,156,capture_loss)
        observations.append(bytes(row))
    catalog=_catalog();catalog["streams"]=[catalog["streams"][0],sample,timing]
    metadata=_metadata();metadata["stream_count"]=3
    if recipe:metadata["firmware_recipe_id"]=recipe
    chunks=[_json_chunk(1,0,metadata),_json_chunk(2,1,catalog),
            _chunk(3,2,_stream_data(2,100,rows,[])),_chunk(3,3,_stream_data(3,224,observations,[]))]
    if footer:
        summary={"clean_shutdown":True,"remote_cleanup_complete":True,"remote_sample_tail_discarded":discarded,
            "remote_tail_windows":[{"node":0,"cessation_status":"confirmed_stop" if confirmed else "unconfirmed",
            "drain_basis":"stop_confirmation_observed_plus_5s" if confirmed else "bounded_uncertain_prefix",
            "source_final_observed":True,"final_sequence":last,"stream_epoch":1,"stop_confirmed_ms":1000,"drain_closed_ms":6000}]}
        chunks.append(_json_chunk(5,4,summary))
    data=FILE_HEADER.pack(FILE_MAGIC_V2,2,0,32,0,0,0)+b"".join(chunks)
    path=tmp_path/"capture.bdq";path.write_bytes(data[:-3] if torn else data);return path


def test_complete_values_and_separate_timing(tmp_path):
    report,decoded=assess_first_imu_recording(recording(tmp_path))
    assert report["file_outcome"]=="complete_delivery"
    assert report["sample_count"]==10 and report["final_sample_raw_observation_present"]
    assert decoded["readings"][0]["ax"]==-32768 and decoded["readings"][-1]["gz"]==-456
    assert report["timing_status"]=="unreconstructed" and report["capacity_qualification"]=="unqualified"
    assert all("time_s" not in row for row in decoded["readings"])
    assert report["metrics"]["sample_delivery"]["denominator"]==10
    assert report["metrics"]["sample_delivery"]["whole_run_missing_percent"]==0
    assert report["verdicts"]["control_stop"] and report["verdicts"]["source_terminal_boundary"]


def test_one_accounted_packet_gap_is_warning(tmp_path):
    report,_=assess_first_imu_recording(recording(tmp_path,gap=True))
    assert report["file_outcome"]=="isolated_five_sample_gap_warning"
    assert report["gaps"]==[{"source_segment_id":1,"first":5,"last":9,"count":5,"extent":"known"}]


@pytest.mark.parametrize("kwargs",[{"footer":False},{"confirmed":False},{"discarded":True},{"torn":True}])
def test_prefix_uncertainty_and_discard_never_claim_delivery(tmp_path,kwargs):
    report,decoded=assess_first_imu_recording(recording(tmp_path,**kwargs))
    assert report["file_outcome"]=="incomplete_or_unresolved"
    assert len(decoded["readings"])==10
    if not kwargs.get("footer",True) or kwargs.get("torn",False):
        # A terminal boundary can exist in a torn file; integrity is independent.
        assert report["verdicts"]["footer_closed"] is False


@pytest.mark.parametrize("key",["source_loss","capture_loss"])
def test_unreconciled_loss_prevents_delivery_or_warning(tmp_path,key):
    report,_=assess_first_imu_recording(recording(tmp_path,**{key:1}))
    assert report["file_outcome"]=="incomplete_or_unresolved" and not report["sample_loss_reconciled"]
    report,_=assess_first_imu_recording(recording(tmp_path,gap=True,**{key:1}))
    assert report["file_outcome"]=="incomplete_or_unresolved"
    report,_=assess_first_imu_recording(recording(tmp_path,gap=True,**{key:5}))
    assert report["file_outcome"]=="isolated_five_sample_gap_warning" and report["sample_loss_reconciled"]


def test_invalid_raw_association_is_separate_from_axes(tmp_path):
    report,decoded=assess_first_imu_recording(recording(tmp_path,valid_raw=False))
    assert report["file_outcome"]=="complete_delivery"
    assert not report["final_sample_raw_observation_present"]
    assert len(decoded["readings"])==10
