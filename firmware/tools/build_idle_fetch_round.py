"""Build the logger-only r21 experiment; retain the tested r20 master and nodes."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from bench_profiles import review_result
from build_master_drain_round import ROOT,CONFIG_SHA,git,sha,NODE_SHA

BASE='f6d2d10cf88b67e94118e3dffb06ae033a6ad13b'
MASTER_SHA='f38b28d881cc91e9f3e3c04b55fa15268f12ab7dbdd97a5079b6f701a08101aa'
LOGGER_SHA='90b579f5718a4e5fbb19e599d77e4b1fa2437d6cf96ad13eb80636d75880c528'
ENV='bodaqs_s3_mini_n4r2_imu_idle_fetch'

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--review',required=True,type=Path)
    p.add_argument('--reference-report',required=True,type=Path)
    args=p.parse_args();out=args.output.resolve();parent=args.parent.resolve()
    if out.exists() or out==ROOT or ROOT in out.parents:p.error('Use fresh output outside source')
    if sys.flags.optimize or os.environ.get('PYTHONOPTIMIZE'):p.error('Acceptance requires assertions enabled')
    head=git('rev-parse','HEAD')
    if git('status','--porcelain'):p.error('Requires committed clean source')
    review=review_result(json.loads(args.review.read_text(encoding='utf-8')),BASE,head)
    for item in review['evidence']:
        if sha(Path(item['path']))!=item['sha256']:p.error('Review evidence checksum mismatch')
    old=json.loads((parent/'BUILD_MANIFEST.json').read_text(encoding='utf-8'))
    if old['status']!='passed' or old['source_commit']!=BASE or old['master_boundary_reserve']!=2:
        p.error('Requires passed r20-r2 parent')
    for line in (parent/'SHA256SUMS.txt').read_text(encoding='utf-8-sig').splitlines():
        digest,name=line.split(maxsplit=1);path=(parent/name).resolve()
        if parent not in path.parents or sha(path)!=digest:p.error('Parent checksum mismatch: '+name)
    for name,digest in [('artifacts/master-boundary-reserve/bodaqs_can_master.out',MASTER_SHA),
        ('artifacts/logger-pipeline/firmware.bin',LOGGER_SHA),('artifacts/fixed-node/bodaqs_can_node.out',NODE_SHA),
        ('Configurations/B_2imu_adc_off.txt',CONFIG_SHA)]:
        if sha(parent/name)!=digest:p.error('Wrong peer/configuration: '+name)
    reference=json.loads((args.reference_report/'assessment.json').read_text(encoding='utf-8'))
    if not reference['diagnostic_precheck_passed'] or reference['payload']['seconds']!=100 or reference['payload']['stored_payload_readings_per_s']!=5854.610000000001:
        p.error('Wrong r20 reference report')
    make='C:/ti/ccs2101/ccs/utils/bin/gmake.exe'
    cc='C:/msys64/ucrt64/bin/gcc.exe';cxx='C:/msys64/ucrt64/bin/g++.exe'
    pio=str(Path.home()/'.platformio/penv/Scripts/pio.exe')
    for path in (make,cc,cxx,pio):
        if not Path(path).is_file():p.error('Missing tool: '+path)
    out.mkdir(parents=True);(out/'logs').mkdir()
    environment=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1',PYTHONIOENCODING='utf-8',PYTHONPATH=str(ROOT/'analysis'))
    environment['PATH']=str(Path(cxx).parent)+os.pathsep+environment['PATH']
    m=dict(schema='bodaqs.pipeline_round.v1',experiment='idle-control-fetch-r21',status='building',
        source_commit=head,reviewed_base=BASE,created_utc=datetime.now(timezone.utc).isoformat(),
        parent_bundle=str(parent),parent_manifest_sha256=sha(parent/'BUILD_MANIFEST.json'),
        logger_env=ENV,configuration_sha256=CONFIG_SHA,expected_nodes=[0,1],minimum_start_spacing_us=600,
        master_boundary_reserve=2,master_optimization_info=[1,0,0],commands=[],artifacts=[],
        qualification='unqualified; physical throughput capture pending',validation_scope='logger',
        unchanged_peers='Master and nodes copied byte-exact from tested r20; no master/node source changes or target rebuilds.',
        node_provenance=old['node_provenance'],
        flash_offsets=old['flash_offsets'],source_archive_scope=['firmware','analysis/bodaqs_analysis','docs','agents.md','GLOSSARY.md','.agents'])
    def save():(out/'BUILD_MANIFEST.json').write_text(json.dumps(m,indent=2)+'\n',encoding='utf-8')
    def copy(source,name,**identity):
        target=out/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
        item=dict(path=name,sha256=sha(target),bytes=target.stat().st_size,**identity);m['artifacts'].append(item);return item
    def run(name,command):
        print(name,flush=True);log=out/'logs'/(name+'.txt');began=time.monotonic()
        with log.open('w',encoding='utf-8') as stream:r=subprocess.run(list(map(str,command)),cwd=ROOT,env=environment,stdout=stream,stderr=subprocess.STDOUT)
        m['commands'].append(dict(name=name,argv=list(map(str,command)),exit_code=r.returncode,seconds=round(time.monotonic()-began,3),log=log.relative_to(out).as_posix(),log_sha256=sha(log)));save()
        if r.returncode:raise RuntimeError(name+' failed: '+str(log))
    try:
        copy(args.review,'review/REVIEW.json')
        for i,item in enumerate(review['evidence']):copy(Path(item['path']),'review/evidence-'+str(i)+'.md')
        for label in ('bodaqs_s3_mini_n4r2',ENV):run('deps-'+label,[pio,'pkg','install','-d','firmware','-e',label])
        run('logger-host',[make,'-B','-C','firmware/test','test','CXX='+cxx,'CC='+cc,'PYTHON='+sys.executable])
        run('logger-clean',[pio,'run','-d','firmware','-e',ENV,'-t','clean'])
        run('logger-idle-fetch',[pio,'run','-d','firmware','-e',ENV,'-j6'])
        folder=ROOT/'firmware/.pio/build'/ENV
        for name in ('firmware.bin','firmware.elf','firmware.map','bootloader.bin','partitions.bin','identity/build-recipe.json'):
            copy(folder/name,'artifacts/logger-idle-fetch/'+name,source_commit=head)
        copy(Path.home()/'.platformio/packages/framework-arduinoespressif32/tools/partitions/boot_app0.bin','artifacts/logger-idle-fetch/boot_app0.bin')
        recipe=json.loads((folder/'identity/build-recipe.json').read_text(encoding='utf-8'))
        before=json.loads((parent/'artifacts/logger-pipeline/identity/build-recipe.json').read_text(encoding='utf-8'))
        def flags(value):return {f for f in value['options']['build_flags'] if not f.startswith('-DBODAQS_FW_NAME=')}
        if flags(recipe)-flags(before)!={'-DBODAQS_RECLAIM_IDLE_CONTROL_FETCH=1'} or flags(before)-flags(recipe):raise ValueError('Unexpected flattened flag delta')
        m['logger_recipe']=recipe['id'];m['rollback_logger_recipe']=before['id']
        for item in old['artifacts']:
            name=item['path']
            if name.startswith('artifacts/master-boundary-reserve/'):relative=name.replace('master-boundary-reserve','fixed-master')
            elif name.startswith('artifacts/logger-pipeline/'):relative=name.replace('logger-pipeline','rollback-logger')
            elif name=='artifacts/fixed-node/bodaqs_can_node.out':relative=name
            else:continue
            copy(parent/name,relative,reused_from=str(parent/name),source_commit=item.get('source_commit'))
        copy(parent/'Configurations/B_2imu_adc_off.txt','Configurations/B_2imu_adc_off.txt',private=True)
        copy(ROOT/'docs/firmware/IMU_Idle_Fetch_Round21.md','RUNBOOK.md')
        copy(parent/'MASTER_TARGET.ccxml','MASTER_TARGET.ccxml')
        curated=dict(reference_bdq='261113_081651.bdq',report_sha256=sha(args.reference_report/'assessment.json'),
            source_boundaries=[n['terminal_sequences'] for n in reference['strict_assessment']['nodes']],
            payload=reference['payload'],earlier_r18_combined_readings_per_s=6124.60,
            whole_source_delivery=reference['strict_assessment']['sample_delivery'])
        (out/'REFERENCE.json').write_text(json.dumps(curated,indent=2)+'\n',encoding='utf-8')
        for source in [*sorted((ROOT/'analysis/bodaqs_analysis').rglob('*.py')),
            *[ROOT/'firmware/tools'/n for n in ('assess_pipeline_round.py','analyze_pipeline_trace.py','assess_master_drain_round.py','assess_imu_optimization.py')]]:
            copy(source,'assessor-source/'+source.relative_to(ROOT).as_posix())
        run('archive-source',['git','archive','--format=zip','-o',out/'SOURCE.zip',head,*m['source_archive_scope']])
        if git('rev-parse','HEAD')!=head or git('status','--porcelain'):raise ValueError('Source changed during build')
        (out/'Results/01-idle-fetch/attempt1').mkdir(parents=True)
        (out/'START_HERE.md').write_text('Read RUNBOOK.md. Logger-only scheduling trial; retain the r20 reserve master and node images/configuration. Device programming is recorded separately in preparation evidence.\n',encoding='utf-8')
        m['status']='passed';save()
    except Exception:
        m['status']='failed';save();raise
    (out/'SHA256SUMS.txt').write_text(''.join(sha(f)+'  '+f.relative_to(out).as_posix()+'\n' for f in sorted(out.rglob('*')) if f.is_file()),encoding='utf-8')
    print('Passed source-bound r21 bundle: '+str(out))

if __name__=='__main__':main()
