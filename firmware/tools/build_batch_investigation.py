"""Build a master-only observation kit. No device access or firmware upload."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
BASE='ff412622cddd6a3e5d93f9ef25495595d5c883b2'
PARENT=ROOT.parent/'imu-idle-fetch-r21'
KIT=ROOT.parent/'imu-four-node-load-r22'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()
def save(p,value):p.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
def checksums(out):
    (out/'SHA256SUMS.txt').write_text(''.join(sha(f)+'  '+f.relative_to(out).as_posix()+'\n'
        for f in sorted(out.rglob('*')) if f.is_file() and f.name!='SHA256SUMS.txt' and 'Results' not in f.relative_to(out).parts),encoding='utf-8')
def verify(parent):
    for line in (parent/'SHA256SUMS.txt').read_text(encoding='utf-8-sig').splitlines():
        digest,name=line.split(maxsplit=1);p=(parent/name.lstrip('*')).resolve()
        if parent.resolve() not in p.parents or sha(p)!=digest:raise ValueError('Input kit mismatch: '+name)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path)
    p.add_argument('--finalize-review',type=Path);args=p.parse_args();out=args.output.resolve()
    if args.finalize_review:
        m=json.loads((out/'BUILD_MANIFEST.json').read_text(encoding='utf-8'))
        r=json.loads(args.finalize_review.read_text(encoding='utf-8'))
        if m['status']!='built_pending_review' or r['base']!=BASE or r['source_commit']!=m['source_commit'] or r['standards']!='passed' or r['spec']!='passed':
            raise ValueError('Review does not approve this exact build')
        verify(out)
        for item in r['evidence']:
            if sha(Path(item['path']))!=item['sha256']:raise ValueError('Review hash mismatch')
            shutil.copyfile(item['path'],out/'review'/Path(item['path']).name)
        shutil.copyfile(args.finalize_review,out/'review/REVIEW.json')
        m['status']='passed';m['review']=r;save(out/'BUILD_MANIFEST.json',m);checksums(out)
        print('Passed reviewed master-only kit: '+str(out));return
    if out.exists() or out==ROOT or ROOT in out.parents:p.error('Use fresh output outside source')
    if git('status','--porcelain'):p.error('Commit source before building')
    head=git('rev-parse','HEAD')
    if subprocess.run(['git','merge-base','--is-ancestor',BASE,head],cwd=ROOT).returncode:p.error('Unexpected base')
    verify(PARENT);verify(KIT)
    old=json.loads((PARENT/'BUILD_MANIFEST.json').read_text(encoding='utf-8'))
    if old['status']!='passed' or old['source_commit']!=BASE:p.error('Unexpected logger parent')
    out.mkdir();(out/'logs').mkdir();(out/'review').mkdir()
    m=dict(schema='bodaqs.batch-investigation-kit.v1',status='building',source_commit=head,base=BASE,
        created_utc=datetime.now(timezone.utc).isoformat(),logger_recipe=old['logger_recipe'],
        parent_manifest_sha256=sha(PARENT/'BUILD_MANIFEST.json'),diagnostic_size_bytes=1448,
        commands=[],device_accessed=False,flashed=False,qualification='unqualified observation round')
    save(out/'BUILD_MANIFEST.json',m)
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
    env['PATH']='C:/msys64/ucrt64/bin'+os.pathsep+env['PATH']
    def run(name,command):
        print(name,flush=True);log=out/'logs'/(name+'.txt')
        with log.open('w',encoding='utf-8') as stream:
            result=subprocess.run(list(map(str,command)),cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT)
        m['commands'].append(dict(name=name,argv=list(map(str,command)),exit_code=result.returncode,log=str(log.relative_to(out))))
        save(out/'BUILD_MANIFEST.json',m)
        if result.returncode:raise RuntimeError('Failed '+name+'; see '+str(log))
    def copy(source,relative):
        dest=out/relative;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dest);return dest
    try:
        make='C:/ti/ccs2101/ccs/utils/bin/gmake.exe';cxx='C:/msys64/ucrt64/bin/g++.exe';cc='C:/msys64/ucrt64/bin/gcc.exe'
        py=[sys.executable,'-B']
        for label,folder in (('common-host','firmware/can-fd/common/test'),('master-host','firmware/can-fd/master/test')):
            run(label,[make,'-B','-C',folder,'test','CXX='+cxx,'CC='+cc,'PYTHON='+sys.executable])
        run('decoder-tests',py+['firmware/tools/test_batch_tools.py'])
        run('master-diagnostic',[make,'-B','-C','firmware/can-fd/master/ticlang',
            'MSPM0_SDK_INSTALL_DIR=C:/ti/mspm0_sdk_2_11_00_07',
            'TICLANG_ARMCOMPILER=C:/ti/ccs2101/ccs/tools/compiler/ti-cgt-armllvm_5.1.1.LTS',
            'SYSCONFIG_TOOL=C:/ti/ccs2101/ccs/utils/sysconfig_1.28.1/sysconfig_cli.bat',
            'CAN_LINK_PROFILE=acquisition','SPI_MEASUREMENT_PROFILE=first-recording','SPI_RX_CAPACITY=2',
            'SPI_PHASE_TIMING=1','SPI_QUEUE_TIMING=1','SPI_TX_PRIME=1','SPI_DISABLED_INIT=1','SPI_BOUNDARY_TRACE=0',
            'SPI_BENCH_MODE=0','MASTER_BLOCK_CRC=0','MASTER_CAN_FIRST=0','MASTER_BOUNDARY_RESERVE=2',
            'CFLAGS_EXTRA=-DBODAQS_MASTER_BATCH_DIAGNOSTICS=1 -fstack-usage'])
        target=ROOT/'firmware/can-fd/master/ticlang'
        for name in ('bodaqs_can_master.out','bodaqs_can_master.map','device_linker.cmd','device.opt'):
            copy(target/name,'artifacts/master-diagnostic/'+name)
        for item in target.glob('*.su'):
            copy(item,'artifacts/master-diagnostic/stack/'+item.name);item.unlink()
        from elftools.elf.elffile import ELFFile
        image=out/'artifacts/master-diagnostic/bodaqs_can_master.out'
        with image.open('rb') as stream:
            elf=ELFFile(stream);symbols=elf.get_section_by_name('.symtab')
            block=symbols.get_symbol_by_name('gMasterBatchInfo')[0]
            section=elf.get_section(block['st_shndx'])
            if block['st_size']!=1448 or section.name!='.bodaqs_spi_buffers':raise ValueError('Diagnostic ABI/placement mismatch')
            for name,wanted in (('gMasterBoundaryReserve',(2).to_bytes(4,'little')),('gMasterOptimizationInfo',b'\1\0\0\0'+bytes(8))):
                symbol=symbols.get_symbol_by_name(name)[0];sec=elf.get_section(symbol['st_shndx']);off=symbol['st_value']-sec['sh_addr']
                if sec.data()[off:off+len(wanted)]!=wanted:raise ValueError('Linked marker mismatch')
            m['linked_audit']=dict(diagnostic_bytes=block['st_size'],diagnostic_section=section.name,
                diagnostic_address=block['st_value'],markers_verified=True)
        m['master']=dict(path=str(image.relative_to(out)).replace('\\','/'),sha256=sha(image))
        copy(PARENT/'artifacts/fixed-master/bodaqs_can_master.out','artifacts/rollback-master/bodaqs_can_master.out')
        copy(PARENT/'MASTER_TARGET.ccxml','MASTER_TARGET.ccxml')
        shutil.copytree(KIT/'Configurations',out/'Configurations')
        shutil.copytree(KIT/'assessor-source',out/'assessor-source')
        for name in ('read_batch_diagnostics.py','assess_batch_investigation.py'):
            copy(ROOT/'firmware/tools'/name,'assessor-source/firmware/tools/'+name)
        copy(ROOT/'firmware/tools/export_batch_diagnostics.js','export_batch_diagnostics.js')
        copy(ROOT/'docs/firmware/IMU_Batch_Investigation_Round23.md','INVESTIGATION.md')
        copy(ROOT/'docs/firmware/IMU_Batch_Investigation_Round23_Runbook.md','RUNBOOK.md')
        case=json.loads((KIT/'CASE_MANIFEST.json').read_text(encoding='utf-8'))
        case.update(parent_bundle=str(PARENT),firmware_source_commit=head,logger_source_commit=BASE,
            master_image_sha256=sha(image),diagnostic_master=True)
        save(out/'CASE_MANIFEST.json',case)
        copy(KIT/'REFERENCE_2IMU.json','REFERENCE_2IMU.json')
        reference=ROOT.parent/'drain-capacity-evidence/first-real-imu-implementation/imu-four-node-load-r22-01-261113_123801-report'
        ref=json.loads((reference/'FACTS.json').read_text(encoding='utf-8'))
        save(out/'REFERENCE_4IMU.json',dict(report=str(reference),facts_sha256=sha(reference/'FACTS.json'),payload=ref['payload'],
            primary_samples_dropped=ref['primary_samples_dropped'],imu_only_bounded_delivery=ref['imu_only_bounded_delivery']))
        run('archive',['git','archive','--format=zip','-o',out/'SOURCE.zip',head,'firmware','docs/firmware/IMU_Batch_Investigation_Round23.md','docs/firmware/IMU_Batch_Investigation_Round23_Runbook.md'])
        if git('status','--porcelain') or git('rev-parse','HEAD')!=head:raise ValueError('Source changed during build')
        (out/'Results/01-observe/attempt1').mkdir(parents=True)
        m['status']='built_pending_review';save(out/'BUILD_MANIFEST.json',m);checksums(out)
        print('Built; review required before use: '+str(out))
    except Exception:
        m['status']='failed';save(out/'BUILD_MANIFEST.json',m);raise
if __name__=='__main__':main()
