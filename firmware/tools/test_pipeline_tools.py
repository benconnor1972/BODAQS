"""Trace loss and tuple ambiguity must remain explicit in offline diagnosis."""
import json
import unittest
from analyze_pipeline_trace import analyze,COLUMNS
from assess_pipeline_round import trace_matches_sources

class PipelineTools(unittest.TestCase):
    def stream(self):
        rows=[dict(type="summary",schema="bodaqs.spi-pipeline.v1",context="9",slots=3)]
        for window in (0,1):
            rows.append(dict(type="window",window=window,count=3,overwritten=0,reason=1,columns=COLUMNS))
            for slot in (1,2,3):
                e={k:0 for k in COLUMNS}
                e.update(slot=slot,target_class=1,target_node=0,target_object=17,target_index=2,
                    response_kind=2 if slot==3 else 0,response_node=0,response_object=17,response_index=2,flags=1,physical_sequence_valid=1)
                rows.append(dict(type="frame",window=window,v=[e[k] for k in COLUMNS]))
        rows.append(dict(type="end"))
        return rows
    def text(self,rows):
        return "\n".join("[PIPE] "+json.dumps(row) for row in rows)
    def test_earlier_duplicate_requests_remain_ambiguous(self):
        result=analyze(self.text(self.stream()))
        self.assertTrue(result["complete"])
        match=result["windows"][0]["reply_correlation_candidates"][0]
        self.assertEqual(match["candidate_slots"],[1,2]) # excludes simultaneous MOSI3
        self.assertEqual((match["minimum_slot_distance"],match["maximum_slot_distance"]),(1,2))
    def test_truncated_export_not_complete(self):
        self.assertFalse(analyze(self.text(self.stream()[:-1]))["complete"])
    def test_missing_row_not_complete(self):
        rows=self.stream();rows.pop(2)
        self.assertFalse(analyze(self.text(rows))["complete"])
    def test_unknown_columns_refused(self):
        rows=self.stream();rows[1]["columns"]=[]
        self.assertFalse(analyze(self.text(rows))["complete"])
    def test_missing_recovery_exchanges_keep_physical_distance(self):
        rows=self.stream()
        for r in rows:
            if r["type"]=="frame" and r["v"][0]==3: r["v"][0]=8
        result=analyze(self.text(rows))
        self.assertTrue(result["complete"])
        self.assertEqual(result["windows"][0]["unobserved_physical_slots_between_valid_rows"],5)
        self.assertEqual(result["windows"][0]["reply_correlation_candidates"][0]["minimum_slot_distance"],6)
    def test_trace_requires_both_exact_source_contexts(self):
        trace=analyze(self.text(self.stream()))
        nodes=[dict(node=n,source=dict(measurement_context="9")) for n in (0,1)]
        self.assertTrue(trace_matches_sources(trace,nodes))
        nodes[1]["source"]["measurement_context"]="10"
        self.assertFalse(trace_matches_sources(trace,nodes))
        self.assertFalse(trace_matches_sources(trace,nodes[:1]))
    def test_truncated_trace_cannot_match_sources(self):
        trace=analyze(self.text(self.stream()[:-1]))
        nodes=[dict(node=n,source=dict(measurement_context="9")) for n in (0,1)]
        self.assertFalse(trace_matches_sources(trace,nodes))

if __name__=="__main__":
    unittest.main()
