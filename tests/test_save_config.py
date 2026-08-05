# tests/test_save_config.py
import unittest
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from services.daq_usb4716.app import app, read_config, write_config

class TestSaveConfigSystem(unittest.TestCase):
    """Deep audit and test of the Save Config System"""

    def setUp(self):
        self.client = app.test_client()
        self.client.testing = True
        self.config_path = os.path.join(PROJECT_ROOT, "services", "daq_usb4716", "config.json")
        # Save original config content to restore after test
        with open(self.config_path, "r", encoding="utf-8") as f:
            self.original_config = json.load(f)

    def tearDown(self):
        # Restore original config content
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.original_config, f, indent=2)

    def test_read_config_function(self):
        cfg = read_config()
        self.assertIsInstance(cfg, dict)
        self.assertIn("CLOCK_RATE", cfg)
        self.assertIn("ENABLE_AI", cfg)
        self.assertIn("ENABLE_DI", cfg)

    def test_write_config_function(self):
        test_data = self.original_config.copy()
        test_data["CLOCK_RATE"] = 2500
        success = write_config(test_data)
        self.assertTrue(success)

        # Read back from disk
        updated_cfg = read_config()
        self.assertEqual(updated_cfg.get("CLOCK_RATE"), 2500)

    def test_post_api_config_endpoint(self):
        payload = self.original_config.copy()
        payload["DI_START_PORT"] = 0
        payload["DI_PORT_COUNT"] = 2
        payload["DI_CHANNEL_OFFSET"] = 100
        payload["SCALE_CONFIGS"]["0"] = {
            "enabled": True,
            "low_voltage": 0.0,
            "high_voltage": 5.0,
            "low_value": -50.0,
            "high_value": 50.0
        }

        response = self.client.post(
            '/api/config',
            data=json.dumps(payload),
            content_type='application/json'
        )

        self.assertEqual(response.status_code, 200)
        resp_data = json.loads(response.data)
        self.assertEqual(resp_data.get("status"), "success")

        # Verify disk persistence
        saved_cfg = read_config()
        self.assertEqual(saved_cfg.get("DI_PORT_COUNT"), 2)
        self.assertEqual(saved_cfg.get("SCALE_CONFIGS", {}).get("0", {}).get("low_value"), -50.0)


if __name__ == '__main__':
    unittest.main()
