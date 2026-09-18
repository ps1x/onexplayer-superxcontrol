import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    'oxp_vram', Path(__file__).resolve().parents[1] / 'oxp-vram.py')
vram = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vram)


class VramTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.device = self.root / 'gpu'
        (self.device / 'uma').mkdir(parents=True)
        (self.device / 'driver').symlink_to(self.root / 'amdgpu')
        (self.device / 'uma/carveout_options').write_text(
            '0: Minimum (512 MB)\n5: Medium (16 GB)\n6: High (32 GB)\n')
        (self.device / 'uma/carveout').write_text('5\n')
        (self.device / 'mem_info_vram_total').write_text(str(16 * 1024**3))
        self.state = self.root / 'request.json'
        self.drm = self.root / 'drm'
        (self.drm / 'card1').mkdir(parents=True)
        (self.drm / 'card1/device').symlink_to(self.device)

    def test_discovery_and_active_size(self):
        self.assertEqual(vram.discover(self.drm), self.device)
        result = vram.status(self.device, self.state)
        self.assertEqual(result['active_bytes'], 16 * 1024**3)
        self.assertEqual(result['options'][0]['label'], '512 MiB')
        self.assertFalse(result['reboot_required'])

    def test_request_does_not_claim_active_size_changed(self):
        result = vram.set_size(self.device, 6, self.state)
        self.assertEqual((self.device / 'uma/carveout').read_text(), '6\n')
        self.assertEqual(result['active_bytes'], 16 * 1024**3)
        self.assertEqual(result['requested']['label'], '32 GiB')
        self.assertTrue(result['reboot_required'])
        self.assertFalse(vram.set_size(self.device, 5, self.state)['reboot_required'])

    def test_invalid_index_never_writes(self):
        for index in [-1, 7, 1000000]:
            with self.assertRaises(ValueError):
                vram.set_size(self.device, index, self.state)
        self.assertEqual((self.device / 'uma/carveout').read_text(), '5\n')
        self.assertFalse(self.state.exists())

    def test_failed_write_preserves_receipt(self):
        snapshot = vram.set_size(self.device, 5, self.state)
        receipt = self.state.read_text()
        control = self.device / 'uma/carveout'
        control.unlink()
        control.symlink_to('/dev/full')
        with patch.object(vram, 'status', return_value=snapshot):
            with self.assertRaises(OSError):
                vram.set_size(self.device, 6, self.state)
        self.assertEqual(self.state.read_text(), receipt)
        self.assertEqual(list(self.root.glob('.oxp-vram-*')), [])

    def test_stale_receipts_are_ignored(self):
        self.state.write_text(json.dumps({'device': '/another/gpu', 'index': 6}))
        self.assertIsNone(vram.status(self.device, self.state)['requested'])
        self.state.write_text('broken json')
        self.assertIsNone(vram.status(self.device, self.state)['requested'])

    def test_unsupported_and_ambiguous_devices(self):
        driver = self.device / 'driver'
        driver.unlink()
        driver.symlink_to(self.root / 'other-driver')
        with self.assertRaises(ValueError):
            vram.discover(self.drm)
        driver.unlink()
        driver.symlink_to(self.root / 'amdgpu')
        import shutil
        shutil.copytree(self.device, self.root / 'gpu2', symlinks=True)
        (self.drm / 'card2').mkdir()
        (self.drm / 'card2/device').symlink_to(self.root / 'gpu2')
        with self.assertRaises(ValueError):
            vram.discover(self.drm)

    def test_bad_options_fail_closed(self):
        for text in ['', '0: Minimum (512 MB)\n0: (1 GB)', '1: unknown', '1: (1 TB)']:
            with self.assertRaises(ValueError):
                vram.parse_options(text)


if __name__ == '__main__':
    unittest.main()
