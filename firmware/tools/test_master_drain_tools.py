"""Protect r19 intake against a repeat of the partial-START false positive."""
import copy
import unittest
from assess_master_drain_round import capture_active

class ActiveSources(unittest.TestCase):
    def valid(self):
        return dict(observed_nodes=[0,1],issues=[],nodes=[
            dict(node=n,sample_count=10,source_identity_present=True,
                effective_configuration_present=True,companion_identity_matches=True,
                metrics=dict(sample_delivery=dict(baseline={"1":0})),file_errors=[])
            for n in (0,1)])

    def test_started_sources_in_any_catalog_order(self):
        a=self.valid()
        self.assertTrue(capture_active(a))
        a["observed_nodes"].reverse()
        a["nodes"].reverse()
        self.assertTrue(capture_active(a))

    def test_descriptors_do_not_prove_start(self):
        for field,value in (("sample_count",0),("source_identity_present",False),
                            ("effective_configuration_present",False),("companion_identity_matches",False),
                            ("metrics",dict(sample_delivery=dict(baseline={}))),
                            ("file_errors",["crc_error"])):
            with self.subTest(field=field):
                a=copy.deepcopy(self.valid())
                a["nodes"][1][field]=value
                self.assertFalse(capture_active(a))

    def test_missing_source_report_refused(self):
        a=self.valid()
        a["nodes"].pop()
        self.assertFalse(capture_active(a))

if __name__=="__main__":
    unittest.main()
