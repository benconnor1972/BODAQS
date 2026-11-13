"""Decode the stopped-owner r23 block. No inferred physical delivery or timing."""
import ctypes as c
import json
from pathlib import Path

U=c.c_uint32
L=c.c_uint64
class Node(c.LittleEndianStructure):
    _fields_=[('sealed',U*2),('retired',U*2),('discarded',U*2),('records',(U*14)*2),('reasons',(U*6)*2),
        ('seal_age_total_ms',L*2),('reception_span_total_ms',L*2),('seal_age_max_ms',U*2),('reception_span_max_ms',U*2),
        ('ingress_at_seal_total',L*2),('residence_total_ms',L*2),('prepared_to_ack_total_ms',L*2),
        ('ingress_at_seal_max',U*2),('residence_max_ms',U*2),('prepared_to_ack_max_ms',U*2),
        ('fresh_preparations',U*2),('repeat_preparations',U*2),('retired_without_all_prepared',U*2),
        *[(n,U) for n in ('last_arrival_ms','sealed_ms','all_prepared_ms','prepared_mask','all_prepared')]]
class Block(c.LittleEndianStructure):
    _fields_=[(n,U) for n in ('version','size_bytes','context_lo','context_hi','session_lo','session_hi',
        'recording_lo','recording_hi','boot_lo','boot_hi')]+[('node',Node*4)]

SIZE=c.sizeof(Block)
if SIZE!=1448:
    raise RuntimeError('Decoder ABI mismatch')
REASONS=('full','class_change','identity_change','reception_span','age','evidence')

def decode(data):
    if len(data)!=SIZE:
        raise ValueError('Incomplete or incompatible binary block')
    b=Block.from_buffer_copy(data)
    if b.version!=1 or b.size_bytes!=SIZE:
        raise ValueError('Unsupported diagnostic layout')
    scope={n:str(getattr(b,n+'_lo')+(getattr(b,n+'_hi')<<32)) for n in ('context','session','recording','boot')}
    if any(v=='0' for v in scope.values()):
        raise ValueError('Missing acquisition scope')
    nodes=[]
    for index,node in enumerate(b.node):
        lanes=[]
        for k,name in enumerate(('samples','evidence')):
            sealed,retired,discarded=node.sealed[k],node.retired[k],node.discarded[k]
            if sum(node.records[k])!=sealed or sum(node.reasons[k])!=sealed or node.records[k][0]:
                raise ValueError('Seal histogram conservation failure')
            if retired+discarded>sealed or node.retired_without_all_prepared[k]>retired:
                raise ValueError('Retirement conservation failure')
            records=sum(i*count for i,count in enumerate(node.records[k]))
            prepared_acks=retired-node.retired_without_all_prepared[k]
            lanes.append(dict(lane=name,sealed=sealed,retired=retired,discarded=discarded,
                unaccounted_sealed_heads=sealed-retired-discarded,
                records_histogram=list(node.records[k]),seal_reasons=dict(zip(REASONS,node.reasons[k])),
                records=records,mean_records_per_sealed_batch=records/sealed if sealed else None,
                mean_seal_age_ms=node.seal_age_total_ms[k]/sealed if sealed else None,
                maximum_seal_age_ms=node.seal_age_max_ms[k],
                mean_reception_span_ms=node.reception_span_total_ms[k]/sealed if sealed else None,
                mean_ingress_depth_at_seal=node.ingress_at_seal_total[k]/sealed if sealed else None,
                maximum_ingress_depth_at_seal=node.ingress_at_seal_max[k],
                mean_sealed_to_ack_ms=node.residence_total_ms[k]/retired if retired else None,
                maximum_sealed_to_ack_ms=node.residence_max_ms[k],
                mean_all_prepared_to_ack_ms=node.prepared_to_ack_total_ms[k]/prepared_acks if prepared_acks else None,
                maximum_all_prepared_to_ack_ms=node.prepared_to_ack_max_ms[k],
                retired_without_all_prepared=node.retired_without_all_prepared[k],
                fresh_fragment_preparations=node.fresh_preparations[k],repeat_fragment_preparations=node.repeat_preparations[k]))
        nodes.append(dict(node=index,lanes=lanes))
    return dict(schema='bodaqs.batch-diagnostics.v1',scope=scope,nodes=nodes,
        limitation='Main-owner software preparation/ACK events through cleanup; no physical delivery, logger acceptance or pure CPU latency inferred.')

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('binary',type=Path)
    args=p.parse_args();print(json.dumps(decode(args.binary.read_bytes()),indent=2))
