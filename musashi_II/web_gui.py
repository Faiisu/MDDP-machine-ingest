# web_gui.py
# Musashi II Web Control Panel (Port 8082)
# See: docs/architecture/context.md
# English comments only

try:
    import eventlet
    eventlet.monkey_patch()
except Exception as _e:
    print(f"[WARNING] Eventlet initialization warning: {_e}")

import os
import sys
import json
import subprocess
import threading
import re
import time
import signal
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit

app = Flask(__name__, template_folder='templates', static_folder='static')
socketio = SocketIO(app, cors_allowed_origins="*")

# State files to persist process metadata across restarts
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, 'config.json')
PID_PATH = os.path.join(BASE_DIR, '.musashi_ii_process.pid')
MODE_PATH = os.path.join(BASE_DIR, '.musashi_ii_process.mode')
DESIRED_STATE_PATH = os.path.join(BASE_DIR, '.musashi_ii_desired_state.json')
LOG_PATH = os.path.join(BASE_DIR, 'musashi_ii_pipeline.log')

# Global monitoring variables
tail_thread = None
stop_tail_event = threading.Event()
last_stats = {}

def read_config():
    """Reads configuration parameters from config.json."""
    default_port = "COM1" if sys.platform == "win32" else "/dev/cu.usbserial-A600bsZD"
    default_config = {
        "serial": {
            "port": default_port,
            "baudrate": 9600,
            "timeout": 2.0,
            "channel": 1
        },
        "database": {
            "db_type": "postgresql",
            "db_name": "mddp_lab",
            "table_name": "musashi_telemetry",
            "host": "100.81.77.113",
            "port": 10001,
            "user": "admin",
            "password": "admin",
            "description": "Database storage for MUSASHI Super ΣCMII Dispenser telemetry data"
        },
        "acquisition": {
            "interval_time": 1,
            "max_retries": 3
        }
    }
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                # Ensure defaults are present for missing sections
                for key in default_config:
                    if key not in cfg:
                        cfg[key] = default_config[key]
                return cfg
    except Exception as e:
        print(f"[ERROR] Reading config.json: {e}")
    return default_config

def write_config(config_data):
    """Writes configuration parameters to config.json."""
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=2)
        return True
    except Exception as e:
        print(f"[ERROR] Writing config.json: {e}")
        return False

def read_desired_state():
    """Reads persistent desired state metadata across reboots."""
    try:
        if os.path.exists(DESIRED_STATE_PATH):
            with open(DESIRED_STATE_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"[ERROR] Reading desired state: {e}")
    return {"is_running": False, "mode": "mockup"}

def write_desired_state(is_running, mode="mockup"):
    """Writes persistent desired state metadata across system reboots."""
    try:
        with open(DESIRED_STATE_PATH, 'w', encoding='utf-8') as f:
            json.dump({"is_running": is_running, "mode": mode}, f, indent=2)
    except Exception as e:
        print(f"[ERROR] Writing desired state: {e}")

# Cross-platform utility to check if a process is still active on the host OS
def is_pid_running(pid):
    if sys.platform == "win32":
        try:
            output = subprocess.check_output(f'tasklist /fi "PID eq {pid}"', shell=True)
            return str(pid) in str(output)
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

# Retrieve the running process info if active
def get_running_process():
    if os.path.exists(PID_PATH) and os.path.exists(MODE_PATH):
        try:
            with open(PID_PATH, 'r') as f:
                pid = int(f.read().strip())
            with open(MODE_PATH, 'r') as f:
                mode = f.read().strip()
            
            if is_pid_running(pid):
                return pid, mode
        except Exception as e:
            print(f"[ERROR] Checking active PID file: {e}")
    return None, None

# Terminate process by PID cross-platform
def terminate_pid(pid):
    if sys.platform == "win32":
        try:
            subprocess.run(f"taskkill /pid {pid} /t /f", shell=True)
        except Exception as e:
            print(f"[ERROR] Terminating Windows PID {pid}: {e}")
    else:
        try:
            os.kill(pid, 15)  # SIGTERM
            for _ in range(30):
                if not is_pid_running(pid):
                    return
                time.sleep(0.1)
            os.kill(pid, 9)   # SIGKILL
        except (ProcessLookupError, OSError):
            pass

# Regex to extract statistics from the log file
# E.g.: [STATS] polled=1 | written=1 | db_errors=0 | pressure_kpa=50.0 | time_ms=250 | vacuum_kpa=0.50 | mode=Sigma Timed | product=PROD_MOCK
STATS_REGEX = re.compile(
    r"\[STATS\] polled=(?P<polled>[0-9,]+) \| written=(?P<written>[0-9,]+) \| db_errors=(?P<errors>[0-9]+) \| pressure_kpa=(?P<press>[0-9\.]+) \| time_ms=(?P<time>[0-9\.]+) \| vacuum_kpa=(?P<vac>[0-9\.]+) \| mode=(?P<mode>[^\|]+) \| product=(?P<prod>.*)"
)

def parse_and_emit_stats(line):
    """Parses stats from a line and updates global caches."""
    global last_stats
    match = STATS_REGEX.search(line)
    if match:
        last_stats = {
            'polled': match.group('polled'),
            'written': match.group('written'),
            'errors': match.group('errors'),
            'pressure_kpa': match.group('press'),
            'time_ms': match.group('time'),
            'vacuum_kpa': match.group('vac'),
            'mode_name': match.group('mode').strip(),
            'product_name': match.group('prod').strip()
        }
        socketio.emit('stats_update', last_stats)

def tail_log_file():
    """Background loop tailing the physical log file to feed sockets."""
    global last_stats
    print("[SYSTEM] Musashi II Log tailing thread started.")
    
    while not os.path.exists(LOG_PATH) and not stop_tail_event.is_set():
        time.sleep(0.2)
        
    try:
        with open(LOG_PATH, 'r', errors='replace') as f:
            f.seek(0, os.SEEK_END)
            
            while not stop_tail_event.is_set():
                pid, _ = get_running_process()
                if pid is None:
                    socketio.emit('status_change', {'is_running': False})
                    if os.path.exists(PID_PATH):
                        try: os.remove(PID_PATH)
                        except: pass
                    if os.path.exists(MODE_PATH):
                        try: os.remove(MODE_PATH)
                        except: pass
                    break
                    
                line = f.readline()
                if not line:
                    time.sleep(0.1)
                    continue
                
                decoded_line = line.strip()
                socketio.emit('log_update', {'log': decoded_line})
                parse_and_emit_stats(decoded_line)
                
    except Exception as e:
        print(f"[ERROR] Error tailing log file: {e}")
    finally:
        print("[SYSTEM] Musashi II Log tailing thread finished.")

def start_tailing():
    """Starts a new background tailing thread if not active."""
    global tail_thread, stop_tail_event
    stop_tail_event.clear()
    if tail_thread is None or not tail_thread.is_alive():
        tail_thread = threading.Thread(target=tail_log_file, daemon=True)
        tail_thread.start()

def get_last_logs(count=50):
    """Retrieves last few log lines for newly connected clients."""
    if not os.path.exists(LOG_PATH):
        return []
    try:
        with open(LOG_PATH, 'r', errors='replace') as f:
            lines = f.readlines()
            return [line.strip() for line in lines[-count:]]
    except Exception as e:
        print(f"[ERROR] Reading historical logs: {e}")
        return []

def scan_host_serial_devices():
    """Scans host PC for connected USB-serial ports and COM interfaces."""
    detected = []
    try:
        import serial.tools.list_ports
        ports = serial.tools.list_ports.comports()
        for p in ports:
            desc = p.description if p.description else p.device
            mfg = getattr(p, 'manufacturer', None) or 'USB Serial Device'
            detected.append({
                'id': p.device,
                'name': f"{p.device} ({desc})",
                'type': 'RS-232 / USB Serial Port',
                'port': p.device,
                'vendor': mfg,
                'hwid': getattr(p, 'hwid', '')
            })
    except Exception as e:
        print(f"[SCAN] Serial port enumeration note: {e}")

    # Fallback default ports for Unix / Windows
    if sys.platform != "win32":
        detected.append({
            'id': '/dev/cu.usbserial-A600bsZD',
            'name': 'Default Musashi RS-232 Port (/dev/cu.usbserial-A600bsZD)',
            'type': 'Configured POSIX Device',
            'port': '/dev/cu.usbserial-A600bsZD',
            'vendor': 'FTDI'
        })
        detected.append({
            'id': '/dev/ttyUSB0',
            'name': 'Linux USB Serial Port (/dev/ttyUSB0)',
            'type': 'Linux TTY Serial',
            'port': '/dev/ttyUSB0',
            'vendor': 'Generic Serial'
        })
    else:
        detected.append({
            'id': 'COM1',
            'name': 'COM1 (Standard Windows Serial Port)',
            'type': 'Windows COM Port',
            'port': 'COM1',
            'vendor': 'System Port'
        })

    detected.append({
        'id': 'MOCK',
        'name': 'MOCK Virtual Hardware (Synthetic Simulation)',
        'type': 'Mockup / Driverless',
        'port': 'MOCK',
        'vendor': 'Software Mock'
    })

    # Deduplicate by 'id'
    seen = set()
    unique = []
    for d in detected:
        if d['id'] not in seen:
            seen.add(d['id'])
            unique.append(d)

    return unique

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/config', methods=['GET'])
def get_config():
    return jsonify(read_config())

@app.route('/api/config', methods=['POST'])
def save_config():
    config_data = request.json
    if not config_data:
        return jsonify({'status': 'error', 'message': 'Invalid payload'}), 400
    if write_config(config_data):
        return jsonify({'status': 'success', 'config': config_data})
    return jsonify({'status': 'error', 'message': 'Failed to save configuration.'}), 500

@app.route('/api/status', methods=['GET'])
def get_status():
    pid, mode = get_running_process()
    cfg = read_config()
    return jsonify({
        'is_running': pid is not None,
        'run_mode': mode or 'mockup',
        'serial_port': cfg.get('serial', {}).get('port', 'N/A'),
        'db_type': cfg.get('database', {}).get('db_type', 'sqlite')
    })

@app.route('/api/scan_serial', methods=['GET'])
def api_scan_serial():
    """Returns JSON list of detected serial interfaces on host PC."""
    devices = scan_host_serial_devices()
    return jsonify({
        'status': 'success',
        'count': len(devices),
        'devices': devices
    })

@app.route('/api/test_db', methods=['POST'])
def test_db():
    req = request.get_json() or {}
    db_cfg = req.get('database') or read_config().get('database', {})
    db_type = db_cfg.get('db_type', 'sqlite')
    
    if db_type in ('postgresql', 'timescaledb'):
        try:
            import psycopg2
            dsn = f"postgresql://{db_cfg.get('user', 'admin')}:{db_cfg.get('password', 'admin')}@{db_cfg.get('host', 'localhost')}:{db_cfg.get('port', 5432)}/{db_cfg.get('db_name', 'mddp_lab')}"
            conn = psycopg2.connect(dsn, connect_timeout=3)
            conn.close()
            return jsonify({'success': True, 'message': f'{db_type.upper()} connection to {db_cfg.get("host")}:{db_cfg.get("port")}/{db_cfg.get("db_name")} successful!'})
        except Exception as e:
            return jsonify({'success': False, 'message': f'{db_type.upper()} connection error: {str(e)}'})
    elif db_type == 'influxdb':
        url = db_cfg.get('influx_url', 'http://localhost:8086').rstrip('/')
        token = db_cfg.get('influx_token', '')
        org = db_cfg.get('influx_org', 'mddp')
        bucket = db_cfg.get('influx_bucket', 'musashi_telemetry')

        target_url = f"{url}/health"
        headers = {"User-Agent": "MusashiII-TestClient"}
        if token:
            headers["Authorization"] = f"Token {token}"

        try:
            import urllib.request
            req_obj = urllib.request.Request(target_url, headers=headers, method="GET")
            with urllib.request.urlopen(req_obj, timeout=3.0) as resp:
                if resp.status in (200, 204):
                    return jsonify({'success': True, 'message': f'InfluxDB server at {url} is HEALTHY! (Org: {org}, Bucket: {bucket})'})
                else:
                    return jsonify({'success': False, 'message': f'InfluxDB returned HTTP status {resp.status}'})
        except Exception as e:
            return jsonify({'success': False, 'message': f'InfluxDB connection error: {str(e)}'})
    else:
        try:
            import sqlite3
            db_name = db_cfg.get('sqlite_path') or db_cfg.get('db_name', 'musashi_data.db')
            db_path = db_name if os.path.isabs(db_name) else os.path.join(BASE_DIR, db_name)
            conn = sqlite3.connect(db_path)
            conn.close()
            return jsonify({'success': True, 'message': f'SQLite connection to {db_name} successful!'})
        except Exception as e:
            return jsonify({'success': False, 'message': f'SQLite connection error: {str(e)}'})

@app.route('/api/test_serial', methods=['POST'])
def test_serial():
    req = request.get_json() or {}
    serial_cfg = req.get('serial') or read_config().get('serial', {})
    port = serial_cfg.get('port', 'MOCK')
    baudrate = int(serial_cfg.get('baudrate', 9600))
    
    if port == 'MOCK':
        return jsonify({'success': True, 'message': 'MOCK serial mode test passed (synthetic hardware).'})
        
    try:
        import serial
        ser = serial.Serial(port=port, baudrate=baudrate, timeout=1.0)
        ser.close()
        return jsonify({'success': True, 'message': f'Serial port {port} opened successfully at {baudrate} bps!'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Serial port {port} test error: {str(e)}'})

@socketio.on('connect')
def handle_connect():
    """Fires when browser client opens or refreshes the page."""
    pid, mode = get_running_process()
    is_active = pid is not None
    cfg = read_config()
    
    # 1. Update client running status immediately
    emit('status_change', {
        'is_running': is_active,
        'mode': mode or 'mockup',
        'port': cfg.get('serial', {}).get('port', 'N/A')
    })
    
    # 2. Feed last stats if process is active
    if is_active and last_stats:
        emit('stats_update', last_stats)
        
    # 3. Stream historical logs so terminal console is populated
    logs = get_last_logs(50)
    for log_line in logs:
        emit('log_update', {'log': log_line})
        
    # Start tailing if a process is already running
    if is_active:
        start_tailing()

@socketio.on('start_musashi')
@socketio.on('start_daq')
def handle_start(data=None):
    """Spawns Musashi II ingestion process in background."""
    data = data or {}
    pid, mode = get_running_process()
    if pid is not None:
        emit('log_update', {'log': '[SYSTEM] Warning: Musashi II ingestion process is already running.'})
        return
        
    run_mode = data.get('mode', 'mockup')
    write_desired_state(True, run_mode)
    
    script_path = os.path.join(BASE_DIR, "read_musashi.py")
    
    cmd = [sys.executable, script_path, "--config", CONFIG_PATH]
    if run_mode == "mockup" or run_mode == "mock":
        cmd.append("--mock")
        
    try:
        # Clear/truncate old log file session
        with open(LOG_PATH, 'w', encoding='utf-8') as f:
            f.write(f"[SYSTEM] Log session initialized for MUSASHI II mode={run_mode.upper()}\n")
            
        log_file = open(LOG_PATH, 'a', encoding='utf-8')
        
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        
        popen_kwargs = dict(
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=env,
        )
        if sys.platform != "win32":
            popen_kwargs["close_fds"] = True
        else:
            popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        proc = subprocess.Popen(cmd, **popen_kwargs)
        log_file.close()
        
        # Persist PID & Mode metadata
        with open(PID_PATH, 'w') as f:
            f.write(str(proc.pid))
        with open(MODE_PATH, 'w') as f:
            f.write(run_mode)
            
        # Update sockets immediately
        socketio.emit('status_change', {'is_running': True, 'mode': run_mode})
        socketio.emit('log_update', {'log': f'[SYSTEM] Spawning Musashi II process (PID: {proc.pid}) mode={run_mode.upper()}'})
        
        # Start log tailer thread
        start_tailing()
        
    except Exception as e:
        socketio.emit('log_update', {'log': f'[SYSTEM] Failed to spawn Musashi II process: {e}'})

@socketio.on('stop_musashi')
@socketio.on('stop_daq')
def handle_stop():
    """Stops the background process by its recorded PID."""
    pid, _ = get_running_process()
    if pid is None:
        socketio.emit('status_change', {'is_running': False})
        emit('log_update', {'log': '[SYSTEM] Warning: Ingestion process is not running. Resetting UI state.'})
        if os.path.exists(PID_PATH):
            try: os.remove(PID_PATH)
            except: pass
        if os.path.exists(MODE_PATH):
            try: os.remove(MODE_PATH)
            except: pass
        return
        
    current_state = read_desired_state()
    write_desired_state(False, current_state.get('mode', 'mockup'))
    socketio.emit('log_update', {'log': f'[SYSTEM] Terminating Musashi II process (PID: {pid})...'})
    
    # 1. Stop log tailing thread
    global stop_tail_event
    stop_tail_event.set()
    
    # 2. Terminate background process
    terminate_pid(pid)
    
    # 3. Clean up metadata files
    if os.path.exists(PID_PATH):
        try: os.remove(PID_PATH)
        except: pass
    if os.path.exists(MODE_PATH):
        try: os.remove(MODE_PATH)
        except: pass
        
    socketio.emit('status_change', {'is_running': False})
    socketio.emit('log_update', {'log': '[SYSTEM] Musashi II Ingestion process terminated.'})

# Initial recovery check on Web GUI startup
pid, mode = get_running_process()
if pid is not None:
    print(f"[SYSTEM] Detected active Musashi II process running (PID: {pid}). Re-attaching...")
    start_tailing()
else:
    desired_state = read_desired_state()
    if desired_state.get('is_running', False):
        saved_mode = desired_state.get('mode', 'mockup')
        print(f"[SYSTEM] System reboot detected! Auto-resuming Musashi II ingestion in MODE={saved_mode.upper()}...")
        handle_start({'mode': saved_mode})

if __name__ == '__main__':
    # Served on Port 8082
    socketio.run(app, host='0.0.0.0', port=8082, debug=False)
