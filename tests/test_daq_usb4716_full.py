# tests/test_daq_usb4716_full.py
import unittest
import json
import os
import sys
from types import SimpleNamespace
import numpy as np

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from services.daq_usb4716.mockup_stream_to_db import DaqSampleParser, Calibrator
from services.daq_usb4716.app import app, read_config


class MockConfig(SimpleNamespace):
    pass


class TestConfigJSON(unittest.TestCase):
    """Verify config.json integrity and schema requirements"""

    def setUp(self):
        self.config_path = os.path.join(PROJECT_ROOT, "services", "daq_usb4716", "config.json")

    def test_config_file_exists(self):
        self.assertTrue(os.path.exists(self.config_path), "config.json must exist")

    def test_config_schema(self):
        with open(self.config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)

        required_keys = [
            "AUTO_START_ON_STARTUP", "AUTO_START_MODE", "DEVICE_DESCRIPTION",
            "PROFILE_PATH", "START_CHANNEL", "CHANNEL_COUNT", "CLOCK_RATE",
            "SECTION_LENGTH", "SECTION_COUNT", "QUEUE_MAXSIZE", "ENABLE_AI",
            "ENABLE_DI", "DI_START_PORT", "DI_PORT_COUNT", "DI_CHANNEL_OFFSET",
            "DESTINATION", "DB_HOST", "DB_PORT", "DB_NAME", "DB_TABLE",
            "SCALE_CONFIGS"
        ]
        for key in required_keys:
            self.assertIn(key, cfg, f"Key '{key}' must be present in config.json")

    def test_scale_configs_structure(self):
        with open(self.config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        scale_cfg = cfg.get("SCALE_CONFIGS", {})
        self.assertIsInstance(scale_cfg, dict, "SCALE_CONFIGS must be a dictionary")
        for ch, params in scale_cfg.items():
            self.assertIn("enabled", params)
            self.assertIn("low_voltage", params)
            self.assertIn("high_voltage", params)
            self.assertIn("low_value", params)
            self.assertIn("high_value", params)


class TestDaqSampleParser(unittest.TestCase):
    """Test AI and DI batch parsing algorithms"""

    def setUp(self):
        self.start_channel = 0
        self.channel_count = 4
        self.clock_rate = 1000
        self.scale_configs = {}
        self.calibrator = Calibrator(self.start_channel, self.channel_count, self.scale_configs)
        self.parser = DaqSampleParser(
            start_channel=self.start_channel,
            channel_count=self.channel_count,
            clock_rate=self.clock_rate,
            calibrator=self.calibrator,
            di_channel_offset=100,
            enable_di=True
        )

    def test_parse_ai_only(self):
        batch_wall_ts_ns = 1700000000000000000
        returned_count = 400
        # 100 samples per channel across 4 channels = 400 floats
        ai_data = np.random.uniform(-5.0, 5.0, returned_count).astype(np.float64)

        rows = self.parser.parse_batch(batch_wall_ts_ns, ai_data, returned_count, di_bytes=None)

        # Total rows should be returned_count = 400
        self.assertEqual(len(rows), 400)
        # Check channel IDs are in 0..3
        channels = set(r[1] for r in rows)
        self.assertEqual(channels, {0, 1, 2, 3})

    def test_parse_di_only(self):
        # AI channels disabled (0 channels)
        calibrator = Calibrator(0, 0, {})
        parser = DaqSampleParser(
            start_channel=0,
            channel_count=0,
            clock_rate=1000,
            calibrator=calibrator,
            di_channel_offset=100,
            enable_di=True
        )

        batch_wall_ts_ns = 1700000000000000000
        returned_count = 100
        di_bytes = bytes([0b10101010])  # Port 0 bit pattern

        rows = parser.parse_batch(batch_wall_ts_ns, None, returned_count, di_bytes=di_bytes)

        # 1 port = 8 bit channels * 500 samples_per_channel = 4000 rows
        self.assertEqual(len(rows), 4000)
        channels = set(r[1] for r in rows)
        expected_channels = set(range(100, 108))
        self.assertEqual(channels, expected_channels)

    def test_parse_dual_ai_and_di(self):
        batch_wall_ts_ns = 1700000000000000000
        returned_count = 200  # 50 samples * 4 channels
        ai_data = np.random.uniform(0.0, 10.0, returned_count).astype(np.float64)
        di_bytes = bytes([0b11110000])

        rows = self.parser.parse_batch(batch_wall_ts_ns, ai_data, returned_count, di_bytes=di_bytes)

        # AI rows = 200, DI rows = 50 samples * 8 bits = 400. Total = 600
        self.assertEqual(len(rows), 600)

    def test_legacy_3tuple_payload(self):
        batch_wall_ts_ns = 1700000000000000000
        returned_count = 40
        ai_data = np.zeros(40, dtype=np.float64)

        rows = self.parser.parse_batch(batch_wall_ts_ns, ai_data, returned_count)
        self.assertEqual(len(rows), 40)


class TestLinearScaling(unittest.TestCase):
    """Test linear calibration scaling equation"""

    def setUp(self):
        self.start_channel = 0
        self.channel_count = 1
        self.clock_rate = 1000
        self.scale_configs = {
            "0": {
                "enabled": True,
                "low_voltage": 0.0,
                "high_voltage": 10.0,
                "low_value": 0.0,
                "high_value": 100.0
            }
        }
        self.calibrator = Calibrator(self.start_channel, self.channel_count, self.scale_configs)
        self.parser = DaqSampleParser(
            start_channel=self.start_channel,
            channel_count=self.channel_count,
            clock_rate=self.clock_rate,
            calibrator=self.calibrator,
            enable_di=False
        )

    def test_linear_scaling_transform(self):
        batch_wall_ts_ns = 1700000000000000000
        returned_count = 1
        # Raw voltage = 5.0 V -> Scaled value should be 50.0
        ai_data = np.array([5.0], dtype=np.float64)

        rows = self.parser.parse_batch(batch_wall_ts_ns, ai_data, returned_count, di_bytes=None)

        self.assertEqual(len(rows), 1)
        scaled_val = rows[0][2]
        self.assertAlmostEqual(scaled_val, 50.0, places=4)

    def test_disabled_scaling(self):
        calibrator = Calibrator(0, 1, {"0": {"enabled": False}})
        parser = DaqSampleParser(0, 1, 1000, calibrator, enable_di=False)

        batch_wall_ts_ns = 1700000000000000000
        ai_data = np.array([7.5], dtype=np.float64)

        rows = parser.parse_batch(batch_wall_ts_ns, ai_data, 1, di_bytes=None)
        self.assertAlmostEqual(rows[0][2], 7.5, places=4)


class TestFlaskAPI(unittest.TestCase):
    """Test Flask Web Control Console API endpoints"""

    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_get_config_api(self):
        response = self.app.get('/api/config')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn('CLOCK_RATE', data)
        self.assertIn('ENABLE_AI', data)
        self.assertIn('ENABLE_DI', data)

    def test_get_status_api(self):
        response = self.app.get('/api/status')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertIn('is_running', data)
        self.assertIn('run_mode', data)

    def test_scan_usb_api(self):
        response = self.app.get('/api/scan_usb')
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data.get('status'), 'success')
        self.assertIn('devices', data)


if __name__ == '__main__':
    unittest.main()
