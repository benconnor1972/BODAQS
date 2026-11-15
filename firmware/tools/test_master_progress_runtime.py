"""Exercise real transfers with diagnostics on/off, independent counter expectations."""
import argparse
import ast
from pathlib import Path
import subprocess
import tempfile

p=argparse.ArgumentParser();p.add_argument('--compiler',default='g++');a=p.parse_args()
root=Path(__file__).resolve().parents[1];common=root/'can-fd/common/protocol'
tree=ast.parse(Path(__file__).with_name('test_ackfetch_direct_runtime.py').read_text())
fixture=next(ast.literal_eval(n.value) for n in ast.walk(tree)
             if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='fixture' for t in n.targets))
fixture=fixture.replace('#include <cassert>',r'''
#include "bodaqs_progress_diagnostics.h"
#include <cassert>
extern "C" uint32_t bodaqs_master_profile_clock(void){return 0;}
extern "C" void bodaqs_master_dispatch_record(uint32_t,uint32_t,uint32_t,uint8_t,uint8_t){}
extern "C" void bodaqs_master_profile_record(uint32_t,uint32_t,uint32_t,uint8_t,uint8_t){}
#if BODAQS_MASTER_PROGRESS_DIAGNOSTICS
volatile BodaqsProgressDiagnostics gMasterProgressInfo;
static_assert(sizeof(BodaqsProgressDiagnostics)==1184,"Wire diagnostic extent");
#endif
''')
fixture=fixture.replace('// A cached evidence ACK',r'''
#if BODAQS_MASTER_PROGRESS_DIAGNOSTICS
 bodaqs_progress_reset(9,77);gMasterProgressInfo.state=2;
#endif
 // A cached evidence ACK''')
fixture=fixture.replace('const auto retired=s.objects_acked;',r'''
#if BODAQS_MASTER_PROGRESS_DIAGNOSTICS
 assert(gMasterProgressInfo.replies[1][2]==2);
 assert(gMasterProgressInfo.replies[1][0]==3); // held, no credit, retired sample
 assert(gMasterProgressInfo.replies[1][7]==3); // bad proof, context, loss notification
 assert(gMasterProgressInfo.node[0].empty_states[0]==1);
 assert(gMasterProgressInfo.node[0].empty_states[3]==1);
 assert(gMasterProgressInfo.node[0].first_preparations==1);
 assert(gMasterProgressInfo.node[0].repeat_preparations==1);
 assert(gMasterProgressInfo.node[0].retired==1);
 assert(gMasterProgressInfo.node[0].prepared_acked==1);
 assert(gMasterProgressInfo.node[0].first_prepare_to_ack_total_ms==171);
 gMasterProgressInfo.state=3;
#endif
 const auto retired=s.objects_acked;''')
fixture=fixture.replace('assert(fwrite(&u.attempts,sizeof u.attempts,1,stdout)==1);',r'''
 assert(fwrite(&u.attempts,sizeof u.attempts,1,stdout)==1);
 s.window=nullptr; // normalize the sole process-dependent address
 assert(fwrite(&s,sizeof s,1,stdout)==1);
 assert(fwrite(&w,sizeof w,1,stdout)==1);
#if BODAQS_MASTER_PROGRESS_DIAGNOSTICS
 assert(gMasterProgressInfo.node[0].retired==1); // frozen duplicate ACK
 // Diagnose distinct empty states without creating or retiring authority.
 s.window=&w;bodaqs_progress_reset(9,77);gMasterProgressInfo.state=2;
 BodaqsMeasurementSlot fetch={};fetch.kind=15;fetch.node=255;fetch.context=9;
 bodaqs_measurement_put(fetch.body,1,4);BodaqsMeasurementSlot empty={};
 u={};u.count=1;u.started_ms=300;
 bodaqs_progress_reply(&s,&fetch,&empty);
 assert(gMasterProgressInfo.node[0].empty_states[5]==1);
 assert(gMasterProgressInfo.node[0].empty_states[8]==0);
 u.object.complete=1;u.object.object=1;fetch.body[4]=1;
 s.ingress[0].count=1;s.receptions[0].next_id[0]=4;
 bodaqs_progress_reply(&s,&fetch,&empty);
 assert(gMasterProgressInfo.node[0].empty_states[3]==1);
 assert(gMasterProgressInfo.node[0].empty_states[6]==1);
 assert(gMasterProgressInfo.node[0].empty_states[7]==1);
 fetch.body[4]=0;bodaqs_progress_reply(&s,&fetch,&empty);
 assert(gMasterProgressInfo.node[0].empty_states[2]==1);
 u.object.object=8;bodaqs_progress_reply(&s,&fetch,&empty);
 assert(gMasterProgressInfo.node[0].empty_states[4]==1);
 assert(gMasterProgressInfo.empty_with_published_samples[1]==3);
 u.count=2;bodaqs_progress_seal(0,&u,320,false);
 assert(gMasterProgressInfo.node[0].sealed_payloads[2]==1);
 assert(gMasterProgressInfo.node[0].seal_reasons[2]==1);
 gMasterProgressInfo.state=3;bodaqs_progress_seal(0,&u,320,false);
 assert(gMasterProgressInfo.node[0].sealed_payloads[2]==1);
 // Real window formation and ACK, not just helper bookkeeping.
 s.loss[0]={};s.isr_loss[0]={};s.ingress[0]={};s.receptions[0]={};w={};
 s.ingress[0].count=1;s.ingress[0].records[0].boot=5;
 s.ingress[0].records[0].received_ms=300;
 bodaqs_progress_reset(9,77);gMasterProgressInfo.state=2;
 out=turn(fetch,300);assert(out.kind==0);
 assert(gMasterProgressInfo.node[0].empty_states[5]==1);
 out=turn(fetch,320);assert(out.kind==2);
 assert(gMasterProgressInfo.node[0].sealed_payloads[1]==1);
 assert(gMasterProgressInfo.node[0].seal_reasons[2]==1);
 assert(gMasterProgressInfo.node[0].seal_age_total_ms==20);
 BodaqsMeasurementSlot proof={};proof.kind=5;proof.context=9;proof.node=0;
 proof.object=out.object;proof.total=out.total;proof.body[0]=1;proof.body[1]=1;
 bodaqs_measurement_put(proof.body+4,bodaqs_measurement_get(out.body+out.total-4,4),4);
 turn(proof,325);
 assert(gMasterProgressInfo.node[0].retired==1);
 assert(gMasterProgressInfo.node[0].receive_to_ack_total_ms==25);
 assert(gMasterProgressInfo.node[0].first_prepare_to_ack_total_ms==5);
 turn(proof,326);assert(gMasterProgressInfo.node[0].retired==1);
 gMasterProgressInfo.state=3;
 BodaqsProgressDiagnostics frozen;memcpy(&frozen,(const void *)&gMasterProgressInfo,sizeof frozen);
 u.attempts=0;bodaqs_progress_prepare(0,&u);bodaqs_progress_seal(0,&u,340,false);
 bodaqs_progress_retire(0,&u,345);bodaqs_progress_reply(&s,&fetch,&empty);
 assert(!memcmp(&frozen,(const void *)&gMasterProgressInfo,sizeof frozen));
#endif
''')
with tempfile.TemporaryDirectory(prefix='bodaqs-progress-') as temporary:
    temp=Path(temporary);cpp=temp/'fixture.cpp';cpp.write_text(fixture,encoding='utf-8')
    outputs=[]
    for enabled in (0,1):
        exe=temp/f'fixture{enabled}.exe'
        subprocess.run([a.compiler,'-std=c++17','-O2','-Wall','-Wextra','-Werror',
            '-DBODAQS_SPI_MEASUREMENT_V4=1','-DBODAQS_SPI_BULK_BYTES=512',
            '-DBODAQS_MASTER_PHASE_TIMING=1',f'-DBODAQS_MASTER_PROGRESS_DIAGNOSTICS={enabled}',
            '-I',str(common),str(cpp),*[str(common/n) for n in (
                'bodaqs_master_service.c','bodaqs_master_protocol.c','bodaqs_control.c','bodaqs_control_exchange.c')],
            '-o',str(exe)],check=True)
        outputs.append(subprocess.check_output([str(exe)]))
    assert outputs[0]==outputs[1][:len(outputs[0])], 'Diagnostics changed full wire or service/window terminal state'
print('Progress counters, credit/held/partial/pinned causes, retirement/freeze and full wire/state equivalence PASS')
