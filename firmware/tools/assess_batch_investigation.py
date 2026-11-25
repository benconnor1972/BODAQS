"""Owned four-source readout retaining the strict primary-stream failure."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from read_batch_diagnostics import decode

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def observation_complete(decoded,assessment):
    sources={n['node']:n for n in assessment['strict_assessment']['nodes']}
    if set(sources)!={0,1,2,3} or not assessment['strict_assessment']['final_summary'].get('remote_cleanup_complete'):
        return False
    for node in decoded['nodes']:
        sample,evidence=node['lanes']
        accepted=sources[node['node']].get('packet_count')
        if not isinstance(accepted,int) or accepted<=0 or not sample['sealed'] or not evidence['sealed'] or sample['records']<accepted:
            return False
        if any(lane['unaccounted_sealed_heads'] for lane in node['lanes']):return False
    return True
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle',type=Path,default=Path(__file__).resolve().parents[3])
    p.add_argument('--case',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();bundle=args.bundle.resolve();out=args.output.resolve()
    if out.exists():p.error('Use a fresh output directory')
    # The pinned r22 reader verifies the kit, takes immutable intake, and keeps
    # primary/source delivery failures. Its expected precheck failure is retained.
    result=subprocess.run([sys.executable,'-B',str(Path(__file__).with_name('assess_four_node_load.py')),
        '--bundle',str(bundle),'--case',str(args.case),'--output',str(out)],
        env=dict(os.environ,PYTHONPATH=str(bundle/'assessor-source/analysis'),PYTHONDONTWRITEBYTECODE='1'))
    if result.returncode not in (0,1) or not (out/'assessment.json').is_file():
        raise RuntimeError('Four-source intake failed')
    assessment=json.loads((out/'assessment.json').read_text(encoding='utf-8'))
    binary=args.case/'master-batch.bin'
    diagnosis=dict(schema='bodaqs.batch-investigation.v1',available=False,scope_matches=False,observations_complete=False,
        strict_recording_precheck_passed=assessment['diagnostic_precheck_passed'],master_image_verified=False)
    if binary.is_file():
        owned=out/binary.name;owned.write_bytes(binary.read_bytes())
        intake=json.loads((out/'INTAKE.json').read_text(encoding='utf-8'))
        intake['files'].append(dict(source=str(binary.resolve()),owned_copy=owned.name,sha256=sha(owned),bytes=owned.stat().st_size))
        (out/'INTAKE.json').write_text(json.dumps(intake,indent=2)+'\n',encoding='utf-8')
        try:
            decoded=decode(owned.read_bytes());diagnosis.update(available=True,diagnostics=decoded)
            scope=decoded['scope'];names={'context':'measurement_context','session':'control_session','recording':'recording_id','boot':'master_boot'}
            nodes=assessment['strict_assessment']['nodes']
            diagnosis['scope_matches']=len(nodes)==4 and all(all(str(n.get('source',{}).get(field))==scope[key] for key,field in names.items()) for n in nodes)
            diagnosis['observations_complete']=observation_complete(decoded,assessment)
        except ValueError as error:
            diagnosis['error']=str(error)
    else:
        diagnosis['error']='Missing master-batch.bin; existing capture facts retained'
        intake=json.loads((out/'INTAKE.json').read_text(encoding='utf-8'))
        intake['missing_inputs'].append('master-batch.bin')
        (out/'INTAKE.json').write_text(json.dumps(intake,indent=2)+'\n',encoding='utf-8')
    (out/'batch-investigation.json').write_text(json.dumps(diagnosis,indent=2)+'\n',encoding='utf-8')
    (out/'SHA256SUMS.txt').write_text(''.join(sha(f)+'  '+f.name+'\n' for f in sorted(out.iterdir()) if f.is_file() and f.name!='SHA256SUMS.txt'),encoding='utf-8')
    print(json.dumps({k:v for k,v in diagnosis.items() if k!='diagnostics'},indent=2))
    return 0 if diagnosis['scope_matches'] and diagnosis['observations_complete'] and assessment['diagnostic_precheck_passed'] else 1
if __name__=='__main__':sys.exit(main())
