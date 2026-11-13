"""Reject malformed snapshots; preserve full 64-bit scope identity."""
import unittest
from read_batch_diagnostics import Block,SIZE,decode

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

if __name__=='__main__':unittest.main()
