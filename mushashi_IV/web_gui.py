# web_gui.py
# Musashi IV Web Control Panel (Port 8083)

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
import sqlite3
import urllib.request
import urllib.parse
import urllib.error
import psycopg2
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit

app = Flask(__name__, template_folder='templates', static_folder='static')
socketio = SocketIO(app, cors_allowed_origins="*")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, 'config.json')
PID_PATH = os.path.join(BASE_DIR, '.musashi_process.pid')
MODE_PATH = os.path.join(BASE_DIR, '.musashi_process.mode')
DESIRED_STATE_PATH = os.path.join(BASE_DIR, '.musashi_desired_state.json')
LOG_PATH = os.path.join(BASE_DIR, 'musashi_iv_pipeline.log')

tail_thread = None
mock_api_process = None
stop_tail_event = threading.Event()
last_stats = {}

def read_config():
    """Reads configuration parameters from config.json."""
    default_config = {
        "API_URL": "http://172.16.48.198:1025/v1/info/channel/data/1",
        "CHANNEL_NO": 1,
        "TIME_INTERVAL": 1.0,
        "DESTINATION": "database",
        "DB_TYPE": "postgresql",
        "DB_HOST": "10.117.8.84",
        "DB_PORT": 10001,
        "DB_NAME": "mddp_lab",
        "DB_USER": "admin",
        "DB_PASSWORD": "admin",
        "DB_TABLE": "musashi_iv_data",
        "DB_DSN": "postgresql://admin:admin@10.117.8.84:10001/mddp_lab",
        "INFLUX_URL": "http://localhost:8086",
        "INFLUX_TOKEN": "my-influx-auth-token",
        "INFLUX_ORG": "mddp",
        "INFLUX_BUCKET": "musashi_telemetry",
        "INFLUX_MEASUREMENT": "musashi_iv_data",
        "SQLITE_PATH": "musashi_iv.db",
        "MOCKUP_DB_DSN": "postgresql://admin:admin@localhost:5432/daq_db",
        "MOCKUP_MODE": True,
        "MOCK_API_PORT": 1025,
        "STATS_INTERVAL_SEC": 5
    }
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
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

def is_pid_running(pid):
    """Checks if a process ID is running on the host OS."""
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

def get_running_process():
    """Retrieves the running process PID and mode if active."""
    if os.path.exists(PID_PATH):
        try:
            with open(PID_PATH, 'r') as f:
                pid = int(f.read().strip())
            mode = "mockup"
            if os.path.exists(MODE_PATH):
                with open(MODE_PATH, 'r') as f:
                    mode = f.read().strip()
            if is_pid_running(pid):
                return pid, mode
        except Exception as e:
            print(f"[ERROR] Checking PID file: {e}")
    return None, None

def terminate_pid(pid):
    """Terminates process by PID across platforms."""
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

STATS_REGEX = re.compile(
    r"\[STATS\] polled=(?P<polled>[0-9,]+) \| written=(?P<written>[0-9,]+) \| db_errors=(?P<errors>[0-9]+) \| last_press=(?P<press>[0-9\.]+) \| last_vac=(?P<vac>[0-9\.]+) \| last_time=(?P<time>[0-9\.]+)"
)

def parse_and_emit_stats(line):
    """Parses stats string emitted by stream_to_db log."""
    global last_stats
    match = STATS_REGEX.search(line)
    if match:
        last_stats = {
            'polled': match.group('polled'),
            'written': match.group('written'),
            'errors': match.group('errors'),
            'dis_press': match.group('press'),
            'dis_vac': match.group('vac'),
            'dis_time': match.group('time')
        }
        socketio.emit('stats_update', last_stats)

def tail_log_file():
    """Tails musashi_iv_pipeline.log in a background thread and emits socket updates."""
    global last_stats
    print("[SYSTEM] Musashi IV Log tailing thread started.")
    while not os.path.exists(LOG_PATH) and not stop_tail_event.is_set():
        time.sleep(0.2)
        
    try:
        with open(LOG_PATH, 'r', errors='replace') as f:
            f.seek(0, os.SEEK_END)
            while not stop_tail_event.is_set():
                pid, _ = get_running_process()
                if pid is None:
                    socketio.emit('status_change', {'is_running': False, 'mode': 'stopped'})
                    if os.path.exists(PID_PATH):
                        try: os.remove(PID_PATH)
                        except: pass
                    if os.path.exists(MODE_PATH):
                        try: os.remove(MODE_PATH)
                        except: pass
                
                line = f.readline()
                if line:
                    clean_line = line.strip()
                    socketio.emit('log_line', {'data': clean_line})
                    socketio.emit('log_update', {'log': clean_line})
                    parse_and_emit_stats(clean_line)
                else:
                    time.sleep(0.1)
    except Exception as e:
        print(f"[SYSTEM] Log tailing error: {e}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/config', methods=['GET'])
def get_config():
    return jsonify(read_config())

@app.route('/api/config', methods=['POST'])
def update_config():
    req_data = request.get_json()
    if not req_data:
        return jsonify({'success': False, 'message': 'Invalid JSON request payload'}), 400
    
    current_cfg = read_config()
    current_cfg.update(req_data)
    
    # Auto-generate DB_DSN from PostgreSQL fields if provided
    if req_data.get('DB_TYPE') == 'postgresql' or current_cfg.get('DB_TYPE') == 'postgresql':
        user = current_cfg.get('DB_USER', 'admin')
        password = current_cfg.get('DB_PASSWORD', 'admin')
        host = current_cfg.get('DB_HOST', 'localhost')
        port = current_cfg.get('DB_PORT', 5432)
        dbname = current_cfg.get('DB_NAME', 'daq_db')
        if user and password and host and port and dbname:
            current_cfg['DB_DSN'] = f"postgresql://{user}:{password}@{host}:{port}/{dbname}"
            
    if write_config(current_cfg):
        return jsonify({'success': True, 'status': 'success', 'message': 'Configuration updated successfully', 'config': current_cfg})
    else:
        return jsonify({'success': False, 'status': 'error', 'message': 'Failed to save configuration'}), 500

@app.route('/api/status', methods=['GET'])
def get_status():
    pid, mode = get_running_process()
    is_running = pid is not None
    return jsonify({
        'is_running': is_running,
        'pid': pid,
        'run_mode': mode or ('mockup' if read_config().get('MOCKUP_MODE', True) else 'real'),
        'config': read_config(),
        'last_stats': last_stats
    })

@app.route('/api/test_db', methods=['POST'])
def test_db():
    req = request.get_json() or {}
    cfg = read_config()
    db_type = req.get('DB_TYPE') or req.get('db_type') or cfg.get('DB_TYPE', 'postgresql')

    if db_type == 'influxdb':
        url = req.get('INFLUX_URL') or req.get('url') or cfg.get('INFLUX_URL', 'http://localhost:8086')
        token = req.get('INFLUX_TOKEN') or req.get('token') or cfg.get('INFLUX_TOKEN', '')
        org = req.get('INFLUX_ORG') or req.get('org') or cfg.get('INFLUX_ORG', 'mddp')
        bucket = req.get('INFLUX_BUCKET') or req.get('bucket') or cfg.get('INFLUX_BUCKET', 'musashi_telemetry')

        target_url = f"{url.rstrip('/')}/health"
        headers = {"User-Agent": "MusashiIV-TestClient"}
        if token:
            headers["Authorization"] = f"Token {token}"

        try:
            req_obj = urllib.request.Request(target_url, headers=headers, method="GET")
            with urllib.request.urlopen(req_obj, timeout=4.0) as resp:
                if resp.status in (200, 204):
                    return jsonify({'success': True, 'message': f'InfluxDB server at {url} is HEALTHY! (Org: {org}, Bucket: {bucket})'})
                else:
                    return jsonify({'success': False, 'message': f'InfluxDB returned HTTP status {resp.status}'})
        except Exception as e:
            # Try secondary endpoint GET /ping
            try:
                ping_url = f"{url.rstrip('/')}/ping"
                ping_req = urllib.request.Request(ping_url, headers=headers, method="GET")
                with urllib.request.urlopen(ping_req, timeout=3.0) as presp:
                    if presp.status in (200, 204):
                        return jsonify({'success': True, 'message': f'InfluxDB server at {url} responded to PING!'})
            except Exception:
                pass
            return jsonify({'success': False, 'message': f'InfluxDB connection error: {str(e)}'})

    elif db_type == 'sqlite':
        db_path = req.get('SQLITE_PATH') or req.get('path') or cfg.get('SQLITE_PATH', 'musashi_iv.db')
        try:
            conn = sqlite3.connect(db_path, timeout=3)
            conn.close()
            return jsonify({'success': True, 'message': f'SQLite file ({db_path}) accessible successfully!'})
        except Exception as e:
            return jsonify({'success': False, 'message': f'SQLite connection error: {str(e)}'})

    else:
        # Default PostgreSQL / TimescaleDB connection check
        dsn = req.get('dsn') or req.get('DB_DSN')
        if not dsn:
            host = req.get('DB_HOST') or cfg.get('DB_HOST', 'localhost')
            port = req.get('DB_PORT') or cfg.get('DB_PORT', 5432)
            user = req.get('DB_USER') or cfg.get('DB_USER', 'admin')
            password = req.get('DB_PASSWORD') or cfg.get('DB_PASSWORD', 'admin')
            dbname = req.get('DB_NAME') or cfg.get('DB_NAME', 'daq_db')
            dsn = f"postgresql://{user}:{password}@{host}:{port}/{dbname}"

        try:
            conn = psycopg2.connect(dsn, connect_timeout=3)
            conn.close()
            return jsonify({'success': True, 'message': 'PostgreSQL/TimescaleDB connection successful!'})
        except Exception as e:
            return jsonify({'success': False, 'message': f'PostgreSQL connection error: {str(e)}'})

@app.route('/api/test_api', methods=['POST'])
def test_api():
    req = request.get_json() or {}
    url = req.get('api_url') or read_config().get('API_URL')
    try:
        req_obj = urllib.request.Request(url, headers={"User-Agent": "MusashiIV-TestClient"})
        with urllib.request.urlopen(req_obj, timeout=3.0) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return jsonify({'success': True, 'message': 'API connected successfully!', 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'message': f'API connection error: {str(e)}'})

@app.route('/api/start', methods=['POST'])
def start_process():
    global tail_thread, stop_tail_event, mock_api_process
    
    pid, current_mode = get_running_process()
    if pid is not None:
        return jsonify({'success': False, 'message': f'Musashi IV ingestion process is already running (PID: {pid})'}), 400

    req_data = request.get_json() or {}
    mode = req_data.get('mode')
    
    cfg = read_config()
    
    if mode == 'mockup':
        cfg['MOCKUP_MODE'] = True
        write_config(cfg)
    elif mode == 'real':
        cfg['MOCKUP_MODE'] = False
        write_config(cfg)
    
    mock_mode = cfg.get("MOCKUP_MODE", True)
    active_mode_str = "mockup" if mock_mode else "real"
    
    if mock_mode:
        try:
            mock_script = os.path.join(BASE_DIR, 'mock_api_server.py')
            mock_api_process = subprocess.Popen([sys.executable, mock_script, str(cfg.get("MOCK_API_PORT", 1025))])
            print("[SYSTEM] Started mock API server on port 1025.")
        except Exception as e:
            print(f"[SYSTEM] Mock API server start notice: {e}")

    log_file = open(LOG_PATH, 'w')
    script_path = os.path.join(BASE_DIR, 'stream_to_db.py')
    
    try:
        proc = subprocess.Popen([sys.executable, script_path], stdout=log_file, stderr=subprocess.STDOUT)
        write_desired_state(True, active_mode_str)
        
        with open(PID_PATH, 'w') as f:
            f.write(str(proc.pid))
        with open(MODE_PATH, 'w') as f:
            f.write(active_mode_str)
            
        stop_tail_event.clear()
        if tail_thread is None or not tail_thread.is_alive():
            tail_thread = threading.Thread(target=tail_log_file, daemon=True)
            tail_thread.start()

        socketio.emit('status_change', {'is_running': True, 'pid': proc.pid, 'mode': active_mode_str})
        return jsonify({'success': True, 'message': f'Musashi IV Ingestion started successfully in [{active_mode_str.upper()}] mode (PID: {proc.pid})', 'pid': proc.pid, 'mode': active_mode_str})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Failed to start ingestion process: {str(e)}'}), 500

@app.route('/api/stop', methods=['POST'])
def stop_process():
    global mock_api_process
    pid, _ = get_running_process()
    if pid is None:
        return jsonify({'success': False, 'message': 'No running process detected'}), 400

    write_desired_state(False)
    terminate_pid(pid)
    if os.path.exists(PID_PATH):
        try: os.remove(PID_PATH)
        except: pass
    if os.path.exists(MODE_PATH):
        try: os.remove(MODE_PATH)
        except: pass
        
    if mock_api_process:
        try:
            mock_api_process.terminate()
            mock_api_process = None
        except: pass

    socketio.emit('status_change', {'is_running': False, 'mode': 'stopped'})
    return jsonify({'success': True, 'message': f'Process {pid} stopped successfully'})

@socketio.on('connect')
def handle_connect():
    pid, mode = get_running_process()
    emit('status_change', {'is_running': pid is not None, 'pid': pid, 'mode': mode or 'stopped'})
    if last_stats:
        emit('stats_update', last_stats)

if __name__ == '__main__':
    print("==========================================================")
    print("      Musashi IV Robot Dispenser Web GUI (Port 8083)")
    print("==========================================================")
    pid, mode = get_running_process()
    if pid is not None:
        print(f"[SYSTEM] Detected active Musashi IV background process (PID: {pid}, Mode: {mode}).")
    else:
        cfg = read_config()
        desired_state = read_desired_state()
        auto_start_enabled = cfg.get('AUTO_START_ON_STARTUP', True)
        is_desired_running = desired_state.get('is_running', False)
        
        if auto_start_enabled or is_desired_running:
            target_mode = cfg.get('AUTO_START_MODE') or (desired_state.get('mode') if is_desired_running else None) or ('mockup' if cfg.get('MOCKUP_MODE', True) else 'real')
            print(f"[SYSTEM] Startup config AUTO_START_ON_STARTUP is enabled. Auto-starting Musashi IV ingestion stream in MODE={target_mode.upper()}...")
            with app.test_request_context(json={'mode': target_mode}):
                start_process()
        else:
            print("[SYSTEM] Startup config AUTO_START_ON_STARTUP is disabled. Awaiting manual start trigger.")
    socketio.run(app, host='0.0.0.0', port=8083, debug=False)
