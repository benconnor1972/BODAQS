"""Dispatch observation validation; hardware cadence remains a bench measurement."""
from pathlib import Path
import subprocess
import tempfile
import unittest

import analyze_spi_probe as probe


class DispatchTraceTests(unittest.TestCase):
    def sample(self):
        r=dict.fromkeys(probe.DISPATCH_COLUMNS,0)
        r.update(begin=1001100,ready_end=1001102,row_end=1001103,start_end=1001104,
                 decision_at=1001105,end=1001110,span_end=1001400,next_row=1003000,
                 last_cs=1000750,last_transfer_end=1000950,row=501,slot=1000,cycles=3,
                 decision=3,pending_before=2,pending_after=2,adc_before=10,adc_after=10,clock_state=3)
        q={**r,"begin":1001500,"ready_end":1001502,"row_end":1001503,"start_end":1001504,
           "decision_at":1001505,"end":1001820,"span_end":1001820,"cycles":1,"decision":4,
           "slot":1001,"pending_after":2,"cs":1001550,"release":1001730,"validate_us":60,
           "expected_us":20,"object_us":30,"request_opcode":2,"request_node":1,
           "request_fragment":4,"request_object":11,"reply_opcode":130,"reply_node":0,
           "reply_fragment":0,"reply_object":12,"reply_status":4}
        t=dict(enabled=True,complete=True,closed=True,start_us=1001000,duration_us=64000,
               capacity=512,record_bytes=96,cycles=4,overflow=0,observed_end_us=1065010,
               window=[1001100,1065010,1000,1001,501,501],
               records=[[r[k] for k in probe.DISPATCH_COLUMNS],[q[k] for k in probe.DISPATCH_COLUMNS]])
        return dict(dispatch_trace=t,elapsed_us=1100000,slots=2000,rows=550,
                    profile=dict(mode="owner_flow",nodes=4,start_interval_us=500),
                    logger_cost=dict(cadence=dict(decisions={k:dict(count=2000) for k in probe.DISPATCH_DECISIONS})),
                    diagnostics=dict(timing={k:dict(total_us=10000) for k in ("validate","expected_crc","object_crc")}))

    def test_observed_and_disabled(self):
        c=self.sample();r=probe.dispatch_trace_report(c)
        self.assertEqual((r['status'],r['exchanges'],r['decision_cycles']['pacing']),('observed',1,3))
        self.assertEqual(r['records'][1]['expected_us'],20)
        c['dispatch_trace'].update(enabled=False,complete=False,closed=False,cycles=0,observed_end_us=0,records=[])
        self.assertEqual(probe.dispatch_trace_report(c)['status'],'disabled')

    def test_partial_and_overflow_are_incomplete(self):
        for changes in (dict(complete=False,closed=False,observed_end_us=0),
                        dict(complete=False,overflow=1,cycles=5)):
            c=self.sample();c['dispatch_trace'].update(changes)
            self.assertEqual(probe.dispatch_trace_report(c)['status'],'incomplete')

    def test_window_conservation_and_off_control(self):
        c=self.sample();t=c['dispatch_trace'];t['window'][3]+=1
        with self.assertRaises(ValueError):probe.dispatch_trace_report(c)
        t.update(enabled=False,complete=False,closed=False,cycles=0,observed_end_us=0,records=[])
        report=probe.dispatch_trace_report(c)
        self.assertEqual(report['status'],'disabled')
        self.assertEqual(report['window_summary']['exchanges'],2)
        self.assertEqual(report['window_summary']['rows'],0)

    def test_corrupted_trace_is_rejected(self):
        for field,value in (('cycles',0),('cycles',2),('decision',4),('reads',1),('pending_before',5),
                            ('span_end',1001000),('begin',1000000),('clock_state',4)):
            c=self.sample();c['dispatch_trace']['records'][0][probe.DISPATCH_COLUMNS.index(field)]=value
            with self.subTest(field=field,value=value),self.assertRaises(ValueError):probe.dispatch_trace_report(c)
        for changes in (dict(complete=False),dict(record_bytes=100),dict(cycles=5),dict(overflow=1),
                        dict(observed_end_us=1064000)):
            c=self.sample();c['dispatch_trace'].update(changes)
            with self.subTest(changes=changes),self.assertRaises(ValueError):probe.dispatch_trace_report(c)

    def test_exchange_identity_cost_continuity_and_pacing(self):
        for field,value in (('request_opcode',6),('pending_before',1),('slot',1002),('row',502),
                            ('validate_us',49),('release',1001900),('cs',1001100),('reply_opcode',256)):
            c=self.sample();c['dispatch_trace']['records'][1][probe.DISPATCH_COLUMNS.index(field)]=value
            with self.subTest(field=field),self.assertRaises(ValueError):probe.dispatch_trace_report(c)

    def test_actual_collector_capacity_reset_and_boundaries(self):
        root=Path(__file__).resolve().parents[1]
        source=r'''
#include "SpiDispatchTrace.h"
#include <cassert>
int main() {
  SpiDispatchTrace t;t.reset(true);
  assert(!t.observe(1000999));assert(t.observe(1001000));
  SpiDispatchRecord r;r.begin=1001000;r.end=r.spanEnd=1001010;r.decision=3;
  t.append(r);r.begin=1001011;r.end=r.spanEnd=1001020;t.append(r);
  assert(t.count==1 && t.cycles==2 && t.records[0].cycles==2 && t.records[0].spanEnd==1001020);
  r.reads=1;t.append(r);assert(t.count==2);r.reads=0;r.decision=4;
  for(unsigned i=2;i<t.kCapacity;++i)t.append(r);
  t.append(r);assert(t.count==512 && t.overflow==1);
  r.decision=3;t.append(r);assert(t.overflow==2 && t.cycles==515);
  assert(!t.observe(1065000) && t.closed && !t.complete());
  t.reset(false);assert(!t.observe(1001000) && !t.count && !t.cycles && !t.overflow && !t.closed);
  t.reset(true);r.decision=3;t.append(r);assert(t.records[0].cycles==1);
  assert(t.observe(1064999));assert(!t.observe(1065000));assert(t.complete());
  assert(!t.observe(1065001));assert(t.observedEnd==1065000);
  t.reset(true);assert(!t.complete() && !t.count);t.append(r);
  t.records[0].cycles=65535;t.append(r);assert(t.count==2);
  static_assert(sizeof(SpiDispatchRecord)==96);
}
'''
        compiler=Path('C:/msys64/ucrt64/bin/g++.exe')
        with tempfile.TemporaryDirectory(prefix='bodaqs-dispatch-') as temp:
            cpp=Path(temp)/'trace.cpp';exe=Path(temp)/'trace.exe';cpp.write_text(source,encoding='utf-8')
            subprocess.run([str(compiler) if compiler.exists() else 'g++','-std=c++17','-DBODAQS_SPI_PROBE=1',
                            '-I',str(root/'src'),str(cpp),'-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True)


if __name__=='__main__':unittest.main()
