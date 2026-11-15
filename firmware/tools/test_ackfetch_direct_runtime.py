"""Exercise combined sample fetch; optional predecessor source is a wire oracle."""
import argparse
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler', default='g++')
    parser.add_argument('--reference', type=Path)
    args = parser.parse_args()
    common = Path(__file__).resolve().parents[1] / 'can-fd/common/protocol'
    fixture = r'''
#include "bodaqs_master_service.h"
#include <cassert>
#include <cstdio>
static BodaqsMasterService s;
static BodaqsMasterWindowStorage w;
static BodaqsMeasurementSlot turn(const BodaqsMeasurementSlot &r,unsigned now=30) {
 uint8_t tx[BODAQS_MEASUREMENT_BYTES],rx[BODAQS_MEASUREMENT_BYTES];
 assert(bodaqs_measurement_encode_request(&r,tx,sizeof tx));
 const auto result=bodaqs_master_service_process_transfer(&s,tx,sizeof tx,now,rx);
 assert(fwrite(&result,sizeof result,1,stdout)==1);
 assert(fwrite(rx,sizeof rx,1,stdout)==1);
 BodaqsMeasurementSlot out={};
 if(result==BODAQS_MASTER_SLOT_PROCESSED) assert(bodaqs_measurement_decode(rx,sizeof rx,&out));
 return out;
}
int main() {
 bodaqs_master_service_init(&s,nullptr);assert(bodaqs_master_service_bind_window(&s,&w));
 s.measurement.mode.phase=2;s.measurement.mode.context=9;s.measurement.mode.session=1;
 s.measurement.mode.recording=77;
 BodaqsMeasurementSlot idle={};idle.node=255;idle.context=9;turn(idle);
 // A cached evidence ACK allows the fetch cases to vary independently.
 auto &ack=s.acknowledged[1][0];ack.complete=1;ack.context=9;ack.object=99;
 ack.node=0;ack.cls=2;ack.total=96;ack.checksum=0x12345678;
 auto &u=w.units[0][0];u.count=BODAQS_SAMPLE_PAYLOADS;
 for(unsigned i=0;i<16U+64U*u.count;++i)u.bytes[i]=uint8_t(i*17+3);
 assert(bodaqs_fragment_seal(&u.object,u.bytes,sizeof u.bytes,9,1,0,1,1,16+64*u.count));
 s.receptions[0].next_id[0]=1;
 BodaqsMeasurementSlot r={};r.kind=14;r.context=9;r.node=0;r.object=99;r.total=96;
 r.body[0]=2;r.body[1]=1;r.body[2]=1;r.body[3]=255;
 bodaqs_measurement_put(r.body+4,ack.checksum,4);
 bodaqs_measurement_put(r.body+16,1,4);
 auto out=turn(r);assert(out.kind==2 && out.retired && out.object==1);
 out=turn(r);assert(out.kind==2 && out.retired); // delayed retirement proof/replay
 r.body[20]=1;out=turn(r);assert(out.kind!=2 && out.retired); // present suppresses repair
 r.body[20]=0;r.body[16]=0;out=turn(r);assert(out.kind!=2 && out.retired); // zero credit
 r.body[16]=1;r.body[4]^=1;out=turn(r);assert(!out.retired && out.kind!=2);
 r.body[4]^=1;r.context=8;out=turn(r);assert(!out.retired && out.kind!=2);
 r.context=9;r.body[21]=1;out=turn(r);assert(!out.retired); // reserved credit bytes
 r.body[21]=0;
 s.loss[0].source=7;out=turn(r,200);assert(out.kind==7 && out.body[1]==9 && out.retired);
 // Retire the sample itself; duplicate proof must not retire it twice.
 r.body[0]=1;r.object=1;r.total=u.object.total;
 bodaqs_measurement_put(r.body+4,u.object.checksum,4);
 out=turn(r,201);assert(out.retired && !u.count && !u.object.complete);
 const auto retired=s.objects_acked;out=turn(r,202);assert(out.retired && s.objects_acked==retired);
 assert(fwrite(&s.objects_acked,sizeof s.objects_acked,1,stdout)==1);
 assert(fwrite(&u.attempts,sizeof u.attempts,1,stdout)==1);
}
'''
    with tempfile.TemporaryDirectory(prefix='bodaqs-direct-fetch-') as tmp:
        temp = Path(tmp)
        cpp = temp / 'fixture.cpp'
        cpp.write_text(fixture, encoding='utf-8')
        for size in (512, 1024):
            outputs = []
            for service in ([args.reference] if args.reference else []) + [common / 'bodaqs_master_service.c']:
                exe = temp / 'fixture.exe'
                subprocess.run([args.compiler, '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror',
                                '-DBODAQS_SPI_MEASUREMENT_V4=1', f'-DBODAQS_SPI_BULK_BYTES={size}',
                                '-I', str(common), str(cpp), str(service),
                                *[str(common / n) for n in ('bodaqs_master_protocol.c', 'bodaqs_control.c',
                                                           'bodaqs_control_exchange.c')], '-o', str(exe)], check=True)
                outputs.append(subprocess.check_output([str(exe)]))
            assert all(o == outputs[0] for o in outputs)
            print(f'{size}: sample/zero/present credit, bad ACK/context/reserved, loss-first, replay and retirement PASS')
            if args.reference:
                print('predecessor full wire and terminal state equivalence PASS')


if __name__ == '__main__':
    main()
