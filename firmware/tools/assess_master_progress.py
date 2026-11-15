"""Read-only r24 raw diagnostics; enforce exact scope and complete reply accounting."""
import argparse
import json
from pathlib import Path
import struct

TARGETS=['idle','sample','evidence','control','protected','master_evidence','ack_only','other']
STATES=['credit_zero','failed_source','eligible_complete','held_complete','outside_credit_complete',
        'partial','ingress_pending','allocation_pinned','no_sample_work']

def assess(case):
    raw=(case/'gMasterProgressInfo.bin').read_bytes()
    if len(raw)!=1184:raise ValueError('Unexpected progress diagnostic extent')
    version,size,state,reserved,context,recording=struct.unpack_from('<4I2Q',raw)
    if (version,size,state,reserved)!=(1,1184,3,0):raise ValueError('Wrong ABI or progress not frozen')
    steady=(case/'gMasterSteadyInfo.bin').read_bytes()
    if len(steady)!=280:raise ValueError('Unexpected steady diagnostic extent')
    s=struct.unpack('<4I2Q5I4I12I16I4x12Q',steady)
    if s[0:4]!=(1,3,1,1) or s[8]<30000000 or s[10]:raise ValueError('Incomplete or invalid steady window')
    if (context,recording)!=s[4:6]:raise ValueError('Progress/steady identity mismatch')
    matrix=struct.unpack_from('<128I',raw,32)
    rows=[list(matrix[i*16:(i+1)*16]) for i in range(8)]
    if [sum(row[c] for row in rows) for c in range(16)]!=list(s[27:43]):
        raise ValueError('Progress/steady reply counts differ')
    if sum(matrix)!=sum(s[11:15]):raise ValueError('Progress/steady request counts differ')
    published=struct.unpack_from('<8I',raw,544)
    nodes=[]
    for n in range(4):
        v=struct.unpack_from('<38I',raw,576+152*n)
        seals=sum(v[:16]);retired=v[21];prepared=v[24]
        nodes.append(dict(node=n,sealed_payloads=list(v[:16]),
            seal_reasons=dict(zip(['full','boundary','age'],v[16:19])),
            sealed=seals,seal_age_mean_ms=v[19]/seals if seals else None,seal_age_max_ms=v[20],
            retired=retired,receive_to_ack_mean_ms=v[22]/retired if retired else None,
            receive_to_ack_max_ms=v[23],prepared_acked=prepared,
            first_prepare_to_ack_mean_ms=v[25]/prepared if prepared else None,
            first_prepare_to_ack_max_ms=v[26],first_preparations=v[27],repeat_preparations=v[28],
            empty_states=dict(zip(STATES,v[29:38]))))
    return dict(schema='bodaqs.master-progress-assessment.v1',context=str(context),recording=str(recording),
        elapsed_us=s[8],requests=sum(matrix),empty_replies=sum(row[0] for row in rows),
        targets={name:dict(requests=sum(rows[i]),replies_by_kind=rows[i],empty=rows[i][0],
            empty_with_published_samples=published[i]) for i,name in enumerate(TARGETS)},nodes=nodes,
        scope='Main-owner prepared replies in full steady window; overlapping post-selection empty states; not physical delivery or duration')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('case',type=Path);a=p.parse_args()
    print(json.dumps(assess(a.case),indent=2))
