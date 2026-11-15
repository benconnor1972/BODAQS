"""Decode bounded MOSI eligibility observations and non-atomic heap point samples."""
import argparse
import json
from pathlib import Path
import sys

REASONS=['outgoing_complete','partial_result','unadmitted_result','pending_first',
         'pending_due','pending_not_due','ack_only','idle']
ARRAYS=['fetches','pending_fetches','age_sum_ms','age_max_ms','first_operation',
        'last_operation','begins','matched','timeouts','matched_age_max_ms','last_opcode','last_page']
MEMORY=['samples','elapsed_us','internal_free','internal_largest','psram_free','psram_largest']
def uint(value,maximum=2**32-1):
    if type(value) is not int or not 0<=value<=maximum:raise ValueError('Invalid unsigned diagnostic field')
    return value
def summarize(t,expected_context):
    if t.get('version')!=1 or t.get('available') is not True:raise ValueError('Control timeline unavailable')
    context=uint(t['context'],2**64-1)
    if context!=expected_context:raise ValueError('Control context mismatch')
    if t['bin_us']!=20000000 or t['capacity']!=36:raise ValueError('Unexpected geometry')
    uint(t['origin_us']);used=max(uint(t['acquisition_used'],36),uint(t['memory_used'],36))
    if len(t['bins'])!=used:raise ValueError('Missing bins')
    rows=[]
    for i,b in enumerate(t['bins']):
        if b['index']!=i:raise ValueError('Nonconsecutive bins')
        for key,length in [('targets',8),('reasons',8),*[(k,4) for k in ARRAYS]]:
            if len(b[key])!=length:raise ValueError('Unexpected array length')
            for v in b[key]:uint(v,2**64-1 if key=='age_sum_ms' else 255 if key in ('last_opcode','last_page') else 2**32-1)
        for k in MEMORY:uint(b['memory'][k])
        if b['memory']['samples']>1:raise ValueError('Expected at most one memory point/bin')
        if not b['memory']['samples'] and any(b['memory'][k] for k in MEMORY):raise ValueError('Unsampled memory payload')
        if b['memory']['samples'] and not i*20000000<=b['memory']['elapsed_us']<(i+1)*20000000:raise ValueError('Memory point outside bin')
        if sum(b['reasons'])!=sum(b['fetches']) or sum(b['reasons'])>b['targets'][3]:raise ValueError('Inconsistent ordinary accounting')
        if any(p>f for p,f in zip(b['pending_fetches'],b['fetches'])):raise ValueError('Inconsistent pending counts')
        for count,total,maximum in zip(b['pending_fetches'],b['age_sum_ms'],b['age_max_ms']):
            if (not count and (total or maximum)) or (count and not maximum<=total<=maximum*count):raise ValueError('Inconsistent pending ages')
        rows.append(dict(start_s=i*20,end_s=(i+1)*20,targets=b['targets'],
            ordinary_reasons=dict(zip(REASONS,b['reasons'])),
            unclassified_ordinary=b['targets'][3]-sum(b['fetches']),
            **{k:b[k] for k in ARRAYS},memory=b['memory'],
            pending_age_mean_ms=[s/n if n else None for s,n in zip(b['age_sum_ms'],b['pending_fetches'])]))
    overflow=uint(t['acquisition_overflow_events'])+uint(t['memory_overflow_events'])
    return dict(schema='bodaqs.control-poll-assessment.v1',context=str(context),origin_us=t['origin_us'],
        complete_capture=not overflow,overflow_events=overflow,rows=rows,
        scope='MOSI attempts; reasons are current-state priority observations, not paired MISO results. Heap fields are separate API point samples, not atomic snapshots or low-water marks.')
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('case',type=Path);a=p.parse_args()
    here=Path(__file__).resolve().parent
    sys.path.insert(0,str(here/'assessor-source' if (here/'assessor-source').exists() else here.parents[1]/'analysis'))
    from bodaqs_analysis.io_bdq import read_bdq
    files=list(a.case.glob('*.bdq'))
    if len(files)!=1:raise ValueError('Expected exactly one finalized BDQ')
    summary=read_bdq(files[0]).final_summary;pressure=summary.get('recording_pressure',{})
    if pressure.get('available') is not True:raise ValueError('Missing retired pressure context')
    print(json.dumps(summarize(summary.get('control_poll_timeline',{}),pressure['context']),indent=2))
