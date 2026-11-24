"""Package checks at the public artifact-audit boundary; no device access."""
import hashlib
from pathlib import Path
import struct
import tempfile
import unittest

from package_a8_production import audit_images, audit_build_timestamp


class PackageAuditTests(unittest.TestCase):
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
            partition = struct.pack('<HBBII16sI', 0x50AA, 0, 0x10, 0x10000,
                                    0x330000, b'app0', 0)
            (root / 'partitions.bin').write_bytes(partition + b'\xff' * 32)
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
            (root / 'partitions.bin').write_bytes(struct.pack(
                '<HBBII16sI', 0x50AA, 0, 0x10, 0x10000, 16, b'app0', 0))
            with self.assertRaisesRegex(ValueError, 'exceeds app partition'):
                audit_images(root)


if __name__ == '__main__':
    unittest.main()
