"""Independent ABI sentinel and invalid-scope tests; no target access."""
import struct
from pathlib import Path
import tempfile
import unittest
from assess_master_progress import assess

class ProgressParserTests(unittest.TestCase):
    def test_layout_and_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);raw=bytearray(1184);steady=bytearray(280)
            identity=(2**63+123,2**54+19)
            struct.pack_into('<4I2Q',raw,0,1,1184,3,0,*identity)
            struct.pack_into('<4I2Q5I',steady,0,1,3,1,1,*identity,0,5000000,30000000,1,0)
            # Evidence request -> empty reply; independent absolute ABI offsets.
            struct.pack_into('<I',raw,32+(2*16)*4,1)
            struct.pack_into('<I',raw,544+2*4,1)
            struct.pack_into('<I',steady,52+2*4,1)
            struct.pack_into('<I',steady,116,1)
            struct.pack_into('<I',raw,576+3*152+21*4,2)
            struct.pack_into('<I',raw,576+3*152+22*4,14)
            struct.pack_into('<I',raw,576+3*152+37*4,11)
            (root/'gMasterProgressInfo.bin').write_bytes(raw)
            (root/'gMasterSteadyInfo.bin').write_bytes(steady)
            result=assess(root)
            self.assertEqual(result['context'],str(identity[0]))
            self.assertEqual(result['recording'],str(identity[1]))
            self.assertEqual(result['targets']['evidence']['empty_with_published_samples'],1)
            self.assertEqual(result['nodes'][3]['receive_to_ack_mean_ms'],7)
            self.assertEqual(result['nodes'][3]['empty_states']['no_sample_work'],11)
            for offset,value in [(8,2),(16,7),(32,2)]:
                broken=bytearray(raw);struct.pack_into('<I',broken,offset,value)
                (root/'gMasterProgressInfo.bin').write_bytes(broken)
                with self.assertRaises(ValueError):assess(root)

if __name__=='__main__':unittest.main()
