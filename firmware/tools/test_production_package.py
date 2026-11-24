"""Package checks at the public artifact-audit boundary; no device access."""
import hashlib
from pathlib import Path
import struct
import tempfile
import unittest

from package_a8_production import audit_images, audit_build_timestamp, public_source_path, audit_merged


def canonical_partitions():
    entries = [(1, 2, 0x9000, 0x5000, b'nvs'), (1, 0, 0xe000, 0x2000, b'otadata'),
               (0, 0x10, 0x10000, 0x3e0000, b'app0'), (1, 3, 0x3f0000, 0x10000, b'coredump')]
    return b''.join(struct.pack('<HBBII16sI', 0x50AA, kind, sub, start, size, label, 0)
                    for kind, sub, start, size, label in entries) + b'\xff' * 32


class PackageAuditTests(unittest.TestCase):
    def test_public_source_archive_excludes_configurations_and_unrelated_files(self):
        for name in ('firmware/src/main.cpp', 'firmware/tools/package_a8_production.py',
                     'firmware/can-fd/node/src/imu_acquisition.c', 'analysis/bodaqs_analysis/__init__.py',
                     'firmware/bodaqs_4mb.csv', 'AGENTS.md'):
            self.assertTrue(public_source_path(name), name)
        for name in ('Configs/wifi.json', 'firmware/Configs/bodaqs-a8/loggercfg.txt',
                     'firmware/dist/BODAQS.zip', 'firmware/can-fd/master/ticlang/old.out',
                     'firmware/tools/private/loggercfg.txt', 'To do/tasks.md',
                     'assets/private.png', 'Examples/logs/session.csv', 'import-manager/app.py'):
            self.assertFalse(public_source_path(name), name)

    def test_merged_recovery_detects_wrong_component_offset_and_gap(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'app.bin').write_bytes(b'app')
            segments = {'app.bin': {'offset': 8, 'end': 11}}
            audit_merged(b'\xff' * 8 + b'app', root, segments)
            for image in (b'\xff' * 7 + b'app\xff', b'\0' + b'\xff' * 7 + b'app'):
                with self.assertRaisesRegex(ValueError, 'merged'):
                    audit_merged(image, root, segments)

    def test_binary_proves_fixed_compiler_timestamp(self):
        audit_build_timestamp(b'header\0Nov 24 2026 00:00:00\0', 1795478400)
        with self.assertRaisesRegex(ValueError, 'timestamp'):
            audit_build_timestamp(b'Nov 25 2026 00:00:00', 1795478400)

    def test_a8_image_offsets_chip_and_actual_hashes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image = bytearray(32)
            image[0] = 0xE9
            image[3] = 0x20  # 4MB flash header
            struct.pack_into('<H', image, 12, 9)  # ESP32-S3
            for name in ('firmware.bin', 'bootloader.bin'):
                (root / name).write_bytes(image)
            (root / 'boot_app0.bin').write_bytes(b'\xff' * 8192)
            (root / 'partitions.bin').write_bytes(canonical_partitions())
            result = audit_images(root)
            self.assertEqual(result['segments']['firmware.bin']['offset'], 0x10000)
            self.assertEqual(result['segments']['bootloader.bin']['chip_id'], 9)
            self.assertEqual(result['segments']['firmware.bin']['sha256'],
                             hashlib.sha256(image).hexdigest())
            image[12] = 0  # ESP32 image must never be accepted for S3
            (root / 'firmware.bin').write_bytes(image)
            with self.assertRaisesRegex(ValueError, 'ESP32-S3'):
                audit_images(root)

    def test_oversized_app_is_rejected_even_when_it_fits_flash(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image = bytearray(32)
            image[0], image[3], image[12] = 0xE9, 0x20, 9
            for name in ('firmware.bin', 'bootloader.bin'):
                (root / name).write_bytes(image)
            (root / 'boot_app0.bin').write_bytes(b'\xff' * 8192)
            (root / 'partitions.bin').write_bytes(canonical_partitions())
            (root / 'firmware.bin').write_bytes(image + b'\xff' * (0x3e0001 - len(image)))
            with self.assertRaisesRegex(ValueError, 'exceeds app partition'):
                audit_images(root)

    def test_wrong_a8_partition_profiles_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image = bytearray(32)
            image[0], image[3], image[12] = 0xe9, 0x20, 9
            for name in ('firmware.bin', 'bootloader.bin', 'boot_app0.bin'):
                (root / name).write_bytes(image)
            original = canonical_partitions()
            variants = {'missing_otadata': original[:32] + original[64:],
                        'missing_coredump': original[:96] + original[128:]}
            for label, index, value in [('wrong_offset', 4, 0xa000),
                                         ('overlap', 36, 0xd000),
                                         ('wrong_app_size', 72, 0x300000),
                                         ('encrypted', 92, 1)]:
                changed = bytearray(original)
                struct.pack_into('<I', changed, index, value)
                variants[label] = changed
            for label, data in variants.items():
                with self.subTest(label=label):
                    (root / 'partitions.bin').write_bytes(data)
                    with self.assertRaises(ValueError):
                        audit_images(root)


if __name__ == '__main__':
    unittest.main()
