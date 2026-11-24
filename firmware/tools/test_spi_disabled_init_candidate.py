import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import build_imu_software_candidate as runner
import test_master_ab_candidate as ab_fixture


class DisabledInitCandidate(unittest.TestCase):
    def test_packages_master_only_control_with_exact_r8_peers(self):
        fixture=ab_fixture.MasterAbCandidate()
        fixture.packaged_fixture(experiment='spi-disabled-init')
        fixture.packaged_fixture(experiment='spi-disabled-init',identical=True)
        fixture.packaged_fixture(experiment='spi-disabled-init',broken='changed-config')

    def test_plan_changes_only_initialization_selector(self):
        with patch.object(sys,'argv',['candidate','--profile','mixed-diagnostic','--experiment','spi-disabled-init',
                                     '--validation-scope','master','--fixed-bundle','fixed']):args=runner.arguments()
        commands=runner.plan(args,Path('out'))
        self.assertEqual([c['name'] for c in commands],['common-host','master-host','candidate-runner-tests','master-init-reference','master-init-disabled'])
        before,after=commands[-2:]
        self.assertEqual([x for x in before['argv'] if not x.startswith('SPI_DISABLED_INIT=')],
                         [x for x in after['argv'] if not x.startswith('SPI_DISABLED_INIT=')])
        self.assertIn('SPI_DISABLED_INIT=0',before['argv']);self.assertIn('SPI_DISABLED_INIT=1',after['argv'])
        self.assertTrue({'SPI_TX_PRIME=1','SPI_BOUNDARY_TRACE=1','SPI_BENCH_MODE=0','SPI_RX_CAPACITY=2'}.issubset(after['argv']))

    def test_rejects_older_bundle_and_wrong_trace_layout(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for value in ({'experiment':'spi-mode-ab'}, {'status':'passed','candidate_profile':'mixed-diagnostic',
                'experiment':'spi-boundary-trace','variants':{'trace':{'spi_mode':0,'spi_tx_prime':True,
                'boundary_trace_version':2,'boundary_trace_bytes':7328}}}):
                (root/'BUILD_MANIFEST.json').write_text(json.dumps(value))
                with self.assertRaises(ValueError):runner.load_fixed_bundle(root,'spi-disabled-init')


if __name__=='__main__':unittest.main()
