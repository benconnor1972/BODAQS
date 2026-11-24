import copy
import unittest
from assess_control_polling import summarize,ARRAYS,MEMORY

class ControlParserTests(unittest.TestCase):
    def test_values_and_invalid_capture(self):
        row={k:[0]*4 for k in ARRAYS};row.update(index=0,targets=[0]*8,reasons=[0]*8,memory=dict.fromkeys(MEMORY,0))
        row['targets'][3]=row['reasons'][4]=row['fetches'][0]=row['pending_fetches'][0]=2
        row['age_sum_ms'][0]=2**32+10;row['age_max_ms'][0]=2**31+5;row['memory'].update(samples=1,internal_free=90,internal_largest=100)
        t=dict(version=1,available=True,context=2**63+123,origin_us=9,bin_us=20000000,capacity=36,
               acquisition_used=1,memory_used=1,acquisition_overflow_events=0,memory_overflow_events=0,bins=[row])
        r=summarize(t,2**63+123);self.assertEqual(r['rows'][0]['pending_age_mean_ms'][0],2**31+5)
        for field,value in [('available',False),('context',123),('capacity',72),('bins',[])]:
            bad=copy.deepcopy(t);bad[field]=value
            with self.assertRaises(ValueError):summarize(bad,2**63+123)
        for field,value in [('targets',[0]*8),('fetches',[0]*4),('last_opcode',[256]*4),('pending_fetches',[3]*4),('age_sum_ms',[0]*4)]:
            bad=copy.deepcopy(t);bad['bins'][0][field]=value
            with self.assertRaises(ValueError):summarize(bad,2**63+123)
        bad=copy.deepcopy(t);bad['memory_overflow_events']=1;self.assertFalse(summarize(bad,2**63+123)['complete_capture'])
        for field,value in [('samples',0),('elapsed_us',20000000)]:
            bad=copy.deepcopy(t);bad['bins'][0]['memory'][field]=value
            with self.assertRaises(ValueError):summarize(bad,2**63+123)

if __name__=='__main__':unittest.main()
