import unittest
from unittest.mock import MagicMock, patch
import sys
import os
import sqlite3
import json

# Dynamic fallback mock for serial module if pyserial is not installed in environment
try:
    import serial
except ImportError:
    mock_serial = MagicMock()
    mock_serial.EIGHTBITS = 8
    mock_serial.PARITY_NONE = 'N'
    mock_serial.STOPBITS_ONE = 1
    sys.modules['serial'] = mock_serial
    import serial

from read_musashi import MusashiDispenser, STX, ETX, EOT, ENQ, ACK, CAN, load_config
from database_handler import DatabaseHandler

class TestMusashiDispenser(unittest.TestCase):
    def setUp(self):
        # Create instance with mocked serial port
        self.patcher = unittest.mock.patch('serial.Serial')
        self.mock_serial_cls = self.patcher.start()
        self.mock_ser = MagicMock()
        self.mock_serial_cls.return_value = self.mock_ser
        self.mock_ser.is_open = True
        
        self.dispenser = MusashiDispenser(port="COM_MOCK")

    def tearDown(self):
        self.patcher.stop()

    def test_checksum_calculation(self):
        """Test two's complement checksum calculation."""
        cs = self.dispenser.compute_checksum("08UL001D01")
        self.assertEqual(cs, "C1")

    def test_build_frame(self):
        """Test frame building format: STX + length + cmd + data + CS + ETX."""
        frame = self.dispenser.build_frame("UL", "001D01")
        expected = b'\x0208UL001D01C1\x03'
        self.assertEqual(frame, expected)

    def test_parse_da01_parameters(self):
        """Test parsing DA01 parameters, specifically extracting pressure P in kPa."""
        payload = "21DA01P0100T00100V0050M0NPROD_00001"
        checksum = self.dispenser.compute_checksum(payload)
        full_frame_str = payload + checksum
        
        parsed = self.dispenser.parse_da01_parameters(full_frame_str)
        
        self.assertEqual(parsed['pressure_raw'], 100)
        self.assertEqual(parsed['pressure_kpa'], 10.0)
        self.assertEqual(parsed['time_ms'], 100)
        self.assertEqual(parsed['vacuum_kpa'], 0.5)
        self.assertEqual(parsed['mode_code'], 0)
        self.assertEqual(parsed['mode_name'], "Timed")
        self.assertEqual(parsed['product_name'], "PROD_00001")

    def test_handshake_upload(self):
        """Test full 10-step handshake upload flow with STX A0 response in Step 4."""
        payload = "21DA01P0500T00250V0100M2NSIGMA_0001"
        checksum = self.dispenser.compute_checksum(payload)
        frame_bytes = STX + (payload + checksum).encode('ascii') + ETX

        a0_frame_bytes = STX + b"02A02D" + ETX

        read_sequence = [
            ACK,       # Step 2: reply to ENQ
        ]
        
        for b in a0_frame_bytes:
            read_sequence.append(bytes([b]))

        read_sequence.append(ENQ)  # Step 6: notification ready to send
        
        for b in frame_bytes:
            read_sequence.append(bytes([b]))
            
        read_sequence.append(EOT)  # Step 10: session end EOT
        
        self.mock_ser.read.side_effect = read_sequence

        result = self.dispenser.read_pressure(channel=1)
        
        self.assertEqual(result['channel'], 1)
        self.assertEqual(result['pressure_kpa'], 50.0)
        self.assertEqual(result['time_ms'], 250)
        self.assertEqual(result['mode_name'], "Sigma Timed")


class TestDatabaseHandler(unittest.TestCase):
    def setUp(self):
        self.test_db_path = "test_musashi_data.db"
        self.db_config = {
            "db_type": "sqlite",
            "db_name": self.test_db_path,
            "table_name": "test_telemetry",
            "description": "Test Database"
        }
        self.db_handler = DatabaseHandler(self.db_config)

    def tearDown(self):
        self.db_handler.close()
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)

    def test_database_init_and_insert(self):
        sample_data = {
            "channel": 1,
            "pressure_kpa": 12.5,
            "pressure_raw": 125,
            "time_ms": 500,
            "time_sec": 0.5,
            "vacuum_kpa": 0.2,
            "mode_code": 0,
            "mode_name": "Timed",
            "product_name": "PROD_TEST",
            "raw_payload": "21DA01P0125T00500V0020M0NPROD_TEST  XX"
        }
        
        row_id = self.db_handler.insert_telemetry(sample_data)
        self.assertIsNotNone(row_id)
        
        # Verify stored record via sqlite query
        conn = sqlite3.connect(self.test_db_path)
        cursor = conn.cursor()
        cursor.execute(f"SELECT channel, pressure_kpa, mode_name, product_name FROM test_telemetry WHERE id=?", (row_id,))
        row = cursor.fetchone()
        conn.close()
        
        self.assertEqual(row[0], 1)
        self.assertEqual(row[1], 12.5)
        self.assertEqual(row[2], "Timed")
        self.assertEqual(row[3], "PROD_TEST")

    def test_load_config(self):
        cfg = load_config("config.json")
        self.assertIn("serial", cfg)
        self.assertIn("database", cfg)
        self.assertIn("acquisition", cfg)
        self.assertIn("interval_time", cfg["acquisition"])
        self.assertIn("description", cfg["database"])

if __name__ == "__main__":
    unittest.main()
