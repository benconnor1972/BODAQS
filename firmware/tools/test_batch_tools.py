"""Reject malformed snapshots; preserve full 64-bit scope identity."""
import unittest
from read_batch_diagnostics import Block,SIZE,decode
from assess_batch_investigation import observation_complete

class SnapshotChecks(unittest.TestCase):
    def valid(self):
        b=Block();b.version=1;b.size_bytes=SIZE
        b.context_lo=123;b.context_hi=0xfedcba98
        b.session_lo=b.recording_lo=b.boot_lo=1
        return b
    def test_scope_is_exact_decimal(self):
        b=self.valid();self.assertEqual(decode(bytes(b))['scope']['context'],str((0xfedcba98<<32)+123))
    def test_layout_and_missing_scope(self):
        for data in (b'',bytes(SIZE),bytes(self.valid())[:-1]):
            with self.assertRaises(ValueError):decode(data)
    def test_histograms_and_retirement(self):
        b=self.valid();b.node[0].sealed[0]=1
        with self.assertRaises(ValueError):decode(bytes(b))
        b.node[0].records[0][13]=1;b.node[0].reasons[0][0]=1
        self.assertEqual(decode(bytes(b))['nodes'][0]['lanes'][0]['unaccounted_sealed_heads'],1)
        b.node[0].retired[0]=1;b.node[0].discarded[0]=1
        with self.assertRaises(ValueError):decode(bytes(b))
    def test_single_shared_head_and_stopped_capture(self):
        b=self.valid();n=b.node[0]
        n.sealed[0]=2;n.records[0][13]=2;n.reasons[0][0]=2
        with self.assertRaises(ValueError):decode(bytes(b))
        n.retired[0]=1;n.sealed[1]=1;n.records[1][1]=1;n.reasons[1][5]=1
        with self.assertRaises(ValueError):decode(bytes(b))
        n.retired[1]=1
        decoded=decode(bytes(b))
        assessment={'strict_assessment':{'nodes':[{'node':i,'packet_count':1} for i in range(4)],'final_summary':{'remote_cleanup_complete':True}}}
        self.assertFalse(observation_complete(decoded,assessment))
        # Exact valid scope alone must not turn an empty block into observations.
        self.assertFalse(observation_complete(decode(bytes(self.valid())),assessment))
    def test_positive_observation_population(self):
        b=self.valid()
        for node in b.node:
            for k in (0,1):
                node.sealed[k]=node.retired[k]=1;node.records[k][1]=1;node.reasons[k][5]=1
        assessment={'strict_assessment':{'nodes':[{'node':i,'packet_count':1} for i in range(4)],'final_summary':{'remote_cleanup_complete':True}}}
        self.assertTrue(observation_complete(decode(bytes(b)),assessment))

if __name__=='__main__':unittest.main()
