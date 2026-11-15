import copy
import unittest
from assess_storage_timeline import summarize,STORAGE,ACQUISITION,ARRAYS

class TimelineParserTests(unittest.TestCase):
    def test_values_and_failures(self):
        context=2**63+123
        s=dict.fromkeys(STORAGE,0);a=dict.fromkeys(ACQUISITION,0)
        for key in ARRAYS:a[key]=[0,0,0,0]
        s.update(writes=1,write_us=200000,write_max_us=200000,slow_writes=1,service_us=201000,non_io_service_us=1000)
        a.update(sample_calls=1,sample_waits=1,evidence_calls=2,evidence_waits=1);a['sample_peak'][3]=128
        t=dict(version=1,available=True,context=context,origin_us=2**32-10,bin_us=20000000,capacity=36,
               storage_used=1,acquisition_used=1,storage_last_elapsed_us=201000,acquisition_last_elapsed_us=1000,
               storage_overflow_events=0,acquisition_overflow_events=0,bins=[dict(index=0,storage=s,acquisition=a)])
        r=summarize(t,context);self.assertEqual(r['context'],str(context));self.assertTrue(r['complete_capture'])
        self.assertEqual(r['rows'][0]['write_mean_ms'],200);self.assertEqual(r['rows'][0]['sample_peak'],[0,0,0,128])
        self.assertEqual(r['rows'][0]['evidence_calls'],2);self.assertEqual(r['rows'][0]['evidence_waits'],1)
        for field,value in [('available',False),('context',123),('capacity',72),('bins',[])]:
            bad=copy.deepcopy(t);bad[field]=value
            with self.assertRaises(ValueError):summarize(bad,context)
        bad=copy.deepcopy(t);bad['bins'][0]['acquisition']['source_loss_reports']=[1]
        with self.assertRaises(ValueError):summarize(bad,context)
        bad=copy.deepcopy(t);bad['storage_overflow_events']=1;self.assertFalse(summarize(bad,context)['complete_capture'])
        bad=copy.deepcopy(t);bad['bins'][0]['storage']['service_time_invalid']=1;self.assertFalse(summarize(bad,context)['complete_capture'])

if __name__=='__main__':unittest.main()
