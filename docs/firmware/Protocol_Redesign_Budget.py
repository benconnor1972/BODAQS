"""Illustrative geometry budget, not a physical-capacity or admission model.

Run with Python -B. No device, filesystem writes or third-party dependencies.
"""
import json
import math

def geometry(nodes,readings,non_axis_bytes,physical,physical_overhead):
    rate=nodes*3333
    object_bytes=readings*12+non_axis_bytes
    fragments=math.ceil(object_bytes/(physical-physical_overhead))
    blocks_per_s=rate/readings
    data_turns=blocks_per_s*fragments
    return dict(nodes=nodes,readings_per_block=readings,object_bytes=object_bytes,
        frame_bytes=physical,fragment_payload_bytes=physical-physical_overhead,
        fragments_per_block=fragments,sample_blocks_per_s=blocks_per_s,
        unique_sample_turns_per_s=data_turns,
        nominal_wire_us_per_frame=physical*8/16,
        nominal_sample_wire_ms_per_s=data_turns*physical*8/16/1000,
        sample_block_bytes_per_s=object_bytes*blocks_per_s,
        assumed_70_percent_sample_turn_share_total_turns_per_s=data_turns/0.7)

def main():
    cases=[]
    for nodes in (2,4):
        # Old geometry has 13 CAN receptions of 76B + 20B header/checksum.
        legacy=geometry(nodes,65,228,256,40)
        assert legacy['object_bytes']==1008 and legacy['fragments_per_block']==5
        legacy['case']='existing_full_reception_geometry';cases.append(legacy)
        # Low-repacking alternative: retain the 13 original 64B sample payloads,
        # omit gateway wrappers, add illustrative 20B shared overhead.
        for size in (256,512):
            grouped=geometry(nodes,65,72,size,40)
            assert grouped['object_bytes']==852
            grouped['case']='illustrative_compact_CAN_payload_group';cases.append(grouped)
        for size in (256,512,1024):
            case=geometry(nodes,70,20,size,40)
            case['case']='illustrative_compact_block_unchanged_physical_overhead'
            cases.append(case)
        # Q19/Q25: one sample unit per transfer. Illustrative 24B total unit
        # metadata/checksum budget plus
        # whole original 64B CAN payloads, each containing five readings.
        for size in (256,512):
            packets=(size-40-24)//64
            unit=geometry(nodes,packets*5,packets*4+24,size,40)
            assert unit['fragments_per_block']==1
            unit['case']='illustrative_self_contained_CAN_payload_unit'
            unit['source_collection_ms']=packets*5/3333*1000
            cases.append(unit)
    four=[c for c in cases if c['nodes']==4]
    compact=[c for c in four if c['case']=='illustrative_compact_block_unchanged_physical_overhead']
    assert [c['fragments_per_block'] for c in compact]==[4,2,1]
    assert len({round(c['nominal_sample_wire_ms_per_s'],8) for c in compact})==1
    print(json.dumps(dict(schema='bodaqs.protocol-redesign-geometry.v1',
        assumptions=['Nominal3333readings/s/source,12raw bytes/six-axis reading.',
            '20B compact logical overhead and70reading block are illustrative, not selected layouts.',
            'Self-contained cases assume24B total logical metadata/checksum plus whole64B CAN sample payloads; Q25 upstream checksum must fit this total or geometry changes. Actual layout is not selected.',
            '40B physical overhead retained for a geometry comparison, not a validated complete protocol budget.',
            '16MHz is requested clock; calculated uninterrupted wire time excludes HAL/pauses/setup.',
            'Full blocks, no retries/repeats/empty transfers.70% sample-turn share is an assumption, not measured service.',
            'Other turn demand does not prove byte/time/CPU utilization; ADC, CAN service, metadata, control, storage and recovery need independent costs.'],
        cases=cases,
        memory_arithmetic=dict(master_bank0_unused_bytes=887,master_bank1_unused_bytes=62280,
            window_2_blocks_per_node_total_bytes=4*2*1024,window_4_blocks_per_node_total_bytes=4*4*1024,
            self_contained_512_window_2_units_per_node_bytes=4*2*512,
            self_contained_512_window_4_units_per_node_bytes=4*4*512,
            limitation='Payload allocation arithmetic only; excludes state/queues/copies/DMA/stack and requires explicit placement.'),
        reference_storage=dict(old_packet_record_bytes_per_s=4*3333/5*100,
            raw_axis_bytes_per_s=4*3333*12,
            limitation='Compact block byte rate in cases excludes BDQ container/record framing and metadata; proposed storage schema is not selected.')),indent=2))

if __name__=='__main__':main()
