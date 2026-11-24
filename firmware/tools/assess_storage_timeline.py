"""Decode r26 final-summary bins; observations, never automatic causal attribution."""
import argparse
import json
from pathlib import Path
import sys

STORAGE=['writes','bytes','write_us','write_max_us','slow_writes','flushes','flush_us','flush_max_us',
         'service_calls','service_us','non_io_service_us','service_max_us','primary_peak','service_gap_max_us','service_time_invalid']
ACQUISITION=['services','service_gap_max_us','gaps_over_10ms','sample_calls','sample_waits','evidence_calls','evidence_waits']
ARRAYS=['sample_peak','evidence_peak','source_loss_reports','evidence_loss_reports']

def integer(v,maximum=2**32-1):
    if type(v) is not int or not 0<=v<=maximum:raise ValueError('Invalid unsigned diagnostic value')
    return v

def summarize(t,expected_context):
    if t.get('version')!=1 or t.get('available') is not True:raise ValueError('Timeline unavailable or unsupported')
    context=integer(t['context'],2**64-1)
    if context!=expected_context:raise ValueError('Timeline/recording context mismatch')
    if t['bin_us']!=20000000 or t['capacity']!=36:raise ValueError('Unexpected timeline geometry')
    for key in ['origin_us','storage_last_elapsed_us','acquisition_last_elapsed_us']:integer(t[key])
    used=max(integer(t['storage_used'],36),integer(t['acquisition_used'],36))
    if len(t['bins'])!=used:raise ValueError('Missing timeline bins')
    rows=[]
    for i,b in enumerate(t['bins']):
        if b['index']!=i:raise ValueError('Nonconsecutive bins')
        s=b['storage'];a=b['acquisition']
        for key in STORAGE:integer(s[key])
        for key in ACQUISITION:integer(a[key])
        for key in ARRAYS:
            if len(a[key])!=4:raise ValueError('Expected four node observations')
            for v in a[key]:integer(v,65535 if key.endswith('peak') else 2**32-1)
        if s['non_io_service_us']>s['service_us'] or a['sample_waits']>a['sample_calls'] or a['evidence_waits']>a['evidence_calls']:
            raise ValueError('Inconsistent timing or callback totals')
        rows.append(dict(index=i,start_s=i*20,end_s=(i+1)*20,
            write_ms=s['write_us']/1000,flush_ms=s['flush_us']/1000,
            service_ms=s['service_us']/1000,non_io_service_ms=s['non_io_service_us']/1000,
            write_mean_ms=s['write_us']/1000/s['writes'] if s['writes'] else None,
            write_max_ms=s['write_max_us']/1000,slow_writes=s['slow_writes'],bytes=s['bytes'],
            primary_peak=s['primary_peak'],sample_peak=a['sample_peak'],evidence_peak=a['evidence_peak'],
            sample_calls=a['sample_calls'],sample_waits=a['sample_waits'],evidence_calls=a['evidence_calls'],evidence_waits=a['evidence_waits'],
            services=a['services'],acquisition_gap_max_ms=a['service_gap_max_us']/1000,
            storage_gap_max_ms=s['service_gap_max_us']/1000,source_loss_report_observations=a['source_loss_reports'],
            evidence_loss_report_observations=a['evidence_loss_reports'],service_time_invalid=s['service_time_invalid']))
    overflow=integer(t['storage_overflow_events'])+integer(t['acquisition_overflow_events'])
    return dict(schema='bodaqs.storage-timeline-assessment.v1',context=str(context),
        origin_us=t['origin_us'],storage_last_elapsed_s=t['storage_last_elapsed_us']/1e6,
        acquisition_last_elapsed_s=t['acquisition_last_elapsed_us']/1e6,
        complete_capture=not overflow and not any(r['service_time_invalid'] for r in rows),
        overflow_events=overflow,rows=rows,
        scope='20s bins; entire operations at start, gaps at end; final bin may be partial; wall time not CPU; loss observations may repeat')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('case',type=Path);a=p.parse_args()
    here=Path(__file__).resolve().parent
    sys.path.insert(0,str(here/'assessor-source' if (here/'assessor-source').exists() else here.parents[1]/'analysis'))
    from bodaqs_analysis.io_bdq import read_bdq
    files=list(a.case.glob('*.bdq'))
    if len(files)!=1:raise ValueError('Expected one finalized BDQ')
    info=read_bdq(files[0]);summary=info.final_summary
    pressure=summary.get('recording_pressure',{})
    if pressure.get('available') is not True:raise ValueError('Missing matching retired pressure context')
    print(json.dumps(summarize(summary.get('recording_timeline',{}),pressure['context']),indent=2))
