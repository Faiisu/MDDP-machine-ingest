import serial
import serial.tools.list_ports
import time
import re
import json
import os
import sys
import argparse
import logging
import datetime
from database_handler import DatabaseHandler

# Ensure UTF-8 output encoding on Windows consoles to prevent UnicodeEncodeError
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# RS-232C Communication Control Codes (Refer to Page 79)
STX = b'\x02'
ETX = b'\x03'
EOT = b'\x04'
ENQ = b'\x05'
ACK = b'\x06'
CAN = b'\x18'

class MusashiDispenser:
    def __init__(self, port, baudrate=9600, timeout=2.0):
        """
        Initializes serial connection to MUSASHI Super ΣCMII dispenser.
        Communication specifications based on Page 78:
        9600 bps (default), 8 data bits, no parity, 1 stop bit.
        """
        self.ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=timeout
        )
        time.sleep(1)  # Allow serial port to initialize
        logger.info(f"Connected to MUSASHI Dispenser on {port} at {baudrate} bps.")

    def close(self):
        """Closes the serial connection."""
        if hasattr(self, 'ser') and self.ser and self.ser.is_open:
            self.ser.close()
            logger.info("Serial connection closed.")

    def compute_checksum(self, payload_str):
        """
        Calculates the 2-character hex checksum as specified on Page 83:
        Subtracted from 0 in 8-bit unsigned modulo 256 for all ASCII characters
        in the character count, command, and data payload.
        """
        csum = 0
        for char in payload_str:
            csum = (csum - ord(char)) & 0xFF
        return f"{csum:02X}"

    def verify_frame_checksum(self, frame_str):
        """
        Verifies the checksum of a frame string (excluding STX and ETX).
        Expected format: [Payload (N chars)][Checksum (2 hex chars)]
        """
        if len(frame_str) < 4:
            raise ValueError(f"Frame too short to contain checksum: '{frame_str}'")
        
        payload = frame_str[:-2]
        recv_checksum = frame_str[-2:].upper()
        calc_checksum = self.compute_checksum(payload)
        
        if recv_checksum != calc_checksum:
            raise ValueError(
                f"Checksum verification failed! Received: '{recv_checksum}', Expected: '{calc_checksum}'"
            )
        return True

    def build_frame(self, command, data=""):
        """
        Builds the command frame matching Page 82 format:
        STX + [2-digit char count] + [Command] + [Data] + [2-digit Checksum] + ETX
        """
        cmd_data = command + data
        # Character count of command + data formatted as 2-digit uppercase hex
        char_count = f"{len(cmd_data):02X}"
        payload = char_count + cmd_data
        checksum = self.compute_checksum(payload)
        
        frame = STX + payload.encode('ascii') + checksum.encode('ascii') + ETX
        return frame

    def read_frame(self, already_read_stx=False):
        """
        Reads a full STX ... ETX frame from the serial buffer.
        Returns the decoded string inside STX and ETX.
        """
        if not already_read_stx:
            b = self.ser.read(1)
            if not b:
                raise Exception("Timeout waiting for response frame STX (0x02).")
            if b != STX:
                raise Exception(f"Protocol error: Expected STX (b'\\x02'), got {b!r}")

        frame_bytes = bytearray()
        while True:
            b = self.ser.read(1)
            if not b:
                raise Exception("Timeout while reading the remainder of the frame.")
            if b == ETX:
                break
            frame_bytes.extend(b)

        return frame_bytes.decode('ascii', errors='ignore')

    def execute_upload_command(self, command="UL", data="001D01"):
        """
        Executes an Upload type command (UL) using the 10-step Handshake Procedure (Page 81).
        """
        self.ser.reset_input_buffer()

        # Step 1: PC sends ENQ
        self.ser.write(ENQ)

        # Step 2: Dispenser replies ACK
        resp = self.ser.read(1)
        if resp != ACK:
            raise Exception(f"Handshake failed at Step 2: Expected ACK (0x06), got: {resp!r}")

        # Step 3: PC sends Upload Command
        frame = self.build_frame(command, data)
        self.ser.write(frame)

        # Step 4: Dispenser replies ACK (0x06) or A0 frame (STX 02 A0 2D ETX)
        resp = self.ser.read(1)
        if not resp:
            raise Exception("Timeout waiting for Dispenser response after sending upload command.")

        if resp == STX:
            # Dispenser returned a frame (A0 confirmation or A2 error)
            cmd_resp_str = self.read_frame(already_read_stx=True)
            self.verify_frame_checksum(cmd_resp_str)
            
            if "A2" in cmd_resp_str[:5]:
                self.ser.write(CAN)
                self.ser.write(EOT)
                raise Exception(f"Command Error (A2) returned by Dispenser: {cmd_resp_str}")
            elif "A0" in cmd_resp_str[:5]:
                # Command accepted with A0 frame! Acknowledge receipt of A0 frame
                self.ser.write(ACK)
            else:
                raise Exception(f"Unexpected response frame in Step 4: {cmd_resp_str}")
        elif resp == ACK:
            # Single byte ACK response, proceed to Step 5
            pass
        else:
            raise Exception(f"Unexpected response byte in Step 4: {resp!r}")

        # Step 5: PC sends EOT
        self.ser.write(EOT)

        # Step 6: Dispenser sends ENQ (0x05) or sends STX data frame directly
        first_byte = self.ser.read(1)
        if not first_byte:
            raise Exception("Timeout waiting for Dispenser upload data response after EOT.")

        if first_byte == ENQ:
            # Step 7: PC replies ACK
            self.ser.write(ACK)

            # Step 8: Dispenser sends Upload Data frame starting with STX
            data_frame_str = self.read_frame(already_read_stx=False)
        elif first_byte == STX:
            # Dispenser sent data frame starting with STX directly after EOT
            data_frame_str = self.read_frame(already_read_stx=True)
        else:
            raise Exception(f"Handshake failed: Expected ENQ (0x05) or STX (0x02), got: {first_byte!r}")

        # Check if returned payload indicates command error A2
        if "A2" in data_frame_str[:5]:
            self.ser.write(CAN)
            self.ser.write(EOT)
            raise Exception(f"Command Error (A2) returned by Dispenser: {data_frame_str}")

        # Verify checksum of received data frame
        self.verify_frame_checksum(data_frame_str)

        # Step 9: PC replies ACK
        self.ser.write(ACK)

        # Step 10: Dispenser sends EOT
        resp_eot = self.ser.read(1)
        if resp_eot and resp_eot != EOT:
            logger.warning(f"Expected EOT (0x04) at Step 10, got: {resp_eot!r}")

        return data_frame_str

    def parse_da01_parameters(self, frame_str):
        """
        Parses DA01 response payload (Dispense parameters):
        Format: 21 DA01 P xxxx T xxxxx V xxxx M x N xxxxxxxxxx CS
        """
        payload = frame_str[:-2]  # strip 2-character checksum at the end
        
        # Remove length prefix (e.g. "21") if present
        if payload.startswith("21"):
            payload = payload[2:]
            
        if not payload.startswith("DA01"):
            raise ValueError(f"Invalid payload format for DA01: '{frame_str}'")
            
        content = payload[4:]  # strip DA01 command prefix
        
        pattern = r"^P(?P<pressure>\d{4})T(?P<time>\d{5})V(?P<vacuum>\d{4})M(?P<mode>\d)N(?P<name>.{10})$"
        match = re.match(pattern, content)
        if not match:
            raise ValueError(f"Failed to parse DA01 parameters pattern from: '{content}'")

        groups = match.groupdict()
        
        p_raw = int(groups['pressure'])
        pressure_kpa = round(p_raw * 0.1, 1)  # 0.1 kPa per unit
        
        t_raw = int(groups['time'])
        time_ms = t_raw  # 1 ms per unit
        
        v_raw = int(groups['vacuum'])
        vacuum_kpa = round(v_raw * 0.01, 2)  # 0.01 kPa per unit
        
        mode_code = int(groups['mode'])
        mode_names = {
            0: "Timed",
            1: "Manual",
            2: "Sigma Timed",
            3: "Sigma Manual"
        }
        mode_name = mode_names.get(mode_code, f"Unknown ({mode_code})")
        
        product_name = groups['name'].rstrip()

        return {
            "pressure_kpa": pressure_kpa,
            "pressure_raw": p_raw,
            "time_ms": time_ms,
            "time_sec": round(time_ms / 1000.0, 3),
            "vacuum_kpa": vacuum_kpa,
            "mode_code": mode_code,
            "mode_name": mode_name,
            "product_name": product_name,
            "raw_payload": frame_str
        }

    def read_pressure(self, channel=1):
        """
        Reads and extracts the pressure value (in kPa) for a given channel (1 to 100).
        """
        if not (1 <= channel <= 100):
            raise ValueError("Channel must be between 1 and 100.")
            
        channel_str = f"{channel:03d}"  # Format as 3 digits (e.g. 001)
        data_param = f"{channel_str}D01"
        
        resp_frame = self.execute_upload_command("UL", data_param)
        parsed = self.parse_da01_parameters(resp_frame)
        parsed["channel"] = channel
        return parsed

    def read_dispense_parameters(self, channel=1):
        """Alias for read_pressure returning full dispensing parameters for a channel."""
        return self.read_pressure(channel=channel)


class MockMusashiDispenser:
    """Mock/Synthetic Musashi dispenser for driver-free & offline hardware testing."""
    def __init__(self, port="MOCK", baudrate=9600, timeout=2.0):
        self.port = port
        self.ser = None
        logger.info("Connected to MOCK MUSASHI Dispenser (Synthetic Simulation Mode).")

    def close(self):
        """Closes mock connection."""
        logger.info("Mock serial connection closed.")

    def read_pressure(self, channel=1):
        import random
        p_raw = random.randint(480, 520)
        time_ms = random.randint(240, 260)
        v_raw = random.randint(45, 55)
        
        pressure_kpa = round(p_raw * 0.1, 1)
        vacuum_kpa = round(v_raw * 0.01, 2)
        
        return {
            "channel": channel,
            "pressure_kpa": pressure_kpa,
            "pressure_raw": p_raw,
            "time_ms": time_ms,
            "time_sec": round(time_ms / 1000.0, 3),
            "vacuum_kpa": vacuum_kpa,
            "mode_code": 2,
            "mode_name": "Sigma Timed",
            "product_name": "PROD_MOCK",
            "raw_payload": f"21DA01P{p_raw:04d}T{time_ms:05d}V{v_raw:04d}M2NPROD_MOCK  00"
        }

    def read_dispense_parameters(self, channel=1):
        return self.read_pressure(channel=channel)


def resolve_serial_port(requested_port):
    """
    Resolves serial port path for cross-platform compatibility (Windows vs macOS/Linux).
    If running on Windows and the configured port is a POSIX path (/dev/...) or unavailable,
    automatically detects active COM ports.
    """
    try:
        available_ports = [p.device for p in serial.tools.list_ports.comports()]
    except Exception:
        available_ports = []

    if sys.platform == "win32" or os.name == "nt":
        if requested_port.startswith("/dev/") or (available_ports and requested_port not in available_ports):
            if available_ports:
                chosen = available_ports[0]
                logger.warning(
                    f"Configured port '{requested_port}' is invalid on Windows. "
                    f"Auto-selected detected port '{chosen}' (Available: {available_ports})"
                )
                return chosen
            else:
                logger.warning(
                    f"Configured port '{requested_port}' is invalid on Windows and no COM ports detected. "
                    f"Defaulting to 'COM1'."
                )
                return "COM1"
    else:
        if requested_port.startswith("COM"):
            if available_ports:
                chosen = available_ports[0]
                logger.warning(
                    f"Configured Windows port '{requested_port}' is invalid on {sys.platform}. "
                    f"Auto-selected detected port '{chosen}' (Available: {available_ports})"
                )
                return chosen

    return requested_port


def load_config(config_path="config.json"):
    """Loads configuration from JSON file or returns default parameters."""
    default_port = "COM1" if sys.platform == "win32" else "/dev/cu.usbserial-A600bsZD"
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    logger.warning(f"Config file '{config_path}' not found. Falling back to default settings.")
    return {
        "serial": {
            "port": default_port,
            "baudrate": 9600,
            "timeout": 2.0,
            "channel": 1
        },
        "database": {
            "db_type": "sqlite",
            "db_name": "musashi_data.db",
            "table_name": "musashi_telemetry",
            "description": "Database storage for MUSASHI Super Sigma CMII Dispenser telemetry data"
        },
        "acquisition": {
            "interval_time": 5.0,
            "max_retries": 3
        }
    }


def run_ingestion_loop(config_path="config.json", max_iterations=None, override_interval=None, override_channel=None, override_port=None, mock_mode=False):
    """
    Main loop that continuously reads telemetry data from MUSASHI dispenser
    and saves it to the database at a configured interval_time.
    """
    config = load_config(config_path)
    
    serial_cfg = config.get("serial", {})
    db_cfg = config.get("database", {})
    acq_cfg = config.get("acquisition", {})

    raw_port = override_port if override_port is not None else serial_cfg.get("port", "COM1" if sys.platform == "win32" else "/dev/cu.usbserial-A600bsZD")
    port = "MOCK" if mock_mode else resolve_serial_port(raw_port)
    baudrate = serial_cfg.get("baudrate", 9600)
    timeout = serial_cfg.get("timeout", 2.0)
    channel = override_channel if override_channel is not None else serial_cfg.get("channel", 1)
    
    interval_time = override_interval if override_interval is not None else acq_cfg.get("interval_time", 5.0)

    print("=" * 65)
    print("      MUSASHI Super Sigma CMII Telemetry Ingestion Service      ")
    print("=" * 65)
    print(f"  Mode:          {'MOCK (Synthetic Hardware Simulation)' if mock_mode else 'REAL (Physical Hardware RS-232)'}")
    print(f"  Serial Port:   {port} @ {baudrate} bps")
    print(f"  Channel:       {channel}")
    print(f"  Interval Time: {interval_time} seconds")
    print(f"  DB Type:       {db_cfg.get('db_type', 'sqlite')}")
    print(f"  DB Name:       {db_cfg.get('db_name', 'musashi_data.db')}")
    print(f"  Table Name:    {db_cfg.get('table_name', 'musashi_telemetry')}")
    print(f"  DB Desc:       {db_cfg.get('description', 'N/A')}")
    print("=" * 65)

    dispenser = None
    db_handler = None

    try:
        if mock_mode:
            dispenser = MockMusashiDispenser(port="MOCK", baudrate=baudrate, timeout=timeout)
        else:
            dispenser = MusashiDispenser(port=port, baudrate=baudrate, timeout=timeout)
            
        db_handler = DatabaseHandler(db_cfg)
        
        iteration = 0
        print(f"\nStarting data collection loop (interval: {interval_time}s). Press Ctrl+C to stop.\n")

        while True:
            iteration += 1
            timestamp_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S %Z")
            print(f"[{timestamp_str}] [Loop #{iteration}] Reading Channel {channel}...")
            
            try:
                data = dispenser.read_pressure(channel=channel)
                row_id = db_handler.insert_telemetry(data)
                
                print(f"  -> Success! Stored record #{row_id} in database.")
                print(f"     Pressure: {data['pressure_kpa']} kPa | Time: {data['time_ms']} ms | Vacuum: {data['vacuum_kpa']} kPa | Mode: {data['mode_name']} | Product: '{data['product_name']}'")
                print(f"[STATS] polled={iteration} | written={iteration} | db_errors=0 | pressure_kpa={data['pressure_kpa']} | time_ms={data['time_ms']} | vacuum_kpa={data['vacuum_kpa']} | mode={data['mode_name']} | product={data['product_name']}")
                sys.stdout.flush()
            except Exception as err:
                logger.error(f"Error acquiring or saving data: {err}")
                sys.stdout.flush()
                if not mock_mode and "Handshake failed" in str(err):
                    logger.warning(
                        f"[HINT] No response received from serial port '{port}'.\n"
                        f"       1. Ensure dispenser unit is powered ON and RS-232 cable is connected.\n"
                        f"       2. Verify port name (e.g., --port COM3 or --port COM4).\n"
                        f"       3. To run in driver-free simulation mode, use: python read_musashi.py --mock"
                    )

            if max_iterations is not None and iteration >= max_iterations:
                print(f"\nReached target iterations limit ({max_iterations}). Exiting loop.")
                break

            print(f"  -> Sleeping for {interval_time} seconds...\n")
            time.sleep(interval_time)

    except KeyboardInterrupt:
        print("\n[STOP] Ingestion loop stopped by user (KeyboardInterrupt). Exiting...")
    except Exception as err:
        logger.error(f"Service encountered an error: {err}")
    finally:
        if dispenser:
            dispenser.close()
        if db_handler:
            db_handler.close()
        print("Service shutdown complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MUSASHI Super Sigma CMII Data Ingestion and Database Service")
    parser.add_argument("--config", type=str, default="config.json", help="Path to config.json file")
    parser.add_argument("--interval", type=float, default=None, help="Override interval time in seconds between iterations")
    parser.add_argument("--channel", type=int, default=None, help="Override channel number (1 - 100)")
    parser.add_argument("--port", type=str, default=None, help="Override serial port (e.g. COM3 or /dev/ttyUSB0)")
    parser.add_argument("--mock", action="store_true", help="Run in mock/simulation mode without physical hardware")
    parser.add_argument("--once", action="store_true", help="Run once instead of infinite loop")
    
    args = parser.parse_args()

    max_iter = 1 if args.once else None
    run_ingestion_loop(
        config_path=args.config,
        max_iterations=max_iter,
        override_interval=args.interval,
        override_channel=args.channel,
        override_port=args.port,
        mock_mode=args.mock
    )