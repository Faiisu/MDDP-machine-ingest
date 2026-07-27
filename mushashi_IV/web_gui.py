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
import urllib.request
import urllib.error
import psycopg2
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit

app = Flask(__name__, template_folder='templates', static_folder='static')
socketio = SocketIO(app, cors_allowed_origins="*")

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.json')
PID_PATH = os.path.join(os.path.dirname(__file__), '.musashi_process.pid')
DESIRED_STATE_PATH = os.path.join(os.path.dirname(__file__), '.musashi_desired_state.json')
LOG_PATH = os.path.join(os.path.dirname(__file__), 'musashi_iv_pipeline.log')

tail_thread = None
mock_api_process = None
stop_tail_event = threading.Event()
last_stats = {}

def read_config():
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"Error reading config.json: {e}")
    return {
        "API_URL": "http://172.16.48.198:1025/v1/info/channel/data/1",
        "CHANNEL_NO": 1,
        "TIME_INTERVAL": 1.0,
        "DESTINATION": "database",
        "DB_DSN": "postgresql://admin:admin@172.21.108.86:5432/daq_db",
        "MOCKUP_DB_DSN": "postgresql://admin:admin@localhost:5432/daq_db",
        "MOCKUP_MODE": True,
        "STATS_INTERVAL_SEC": 5
    }

def write_config(config_data):
    try:
        with open(CONFIG_PATH, 'w') as f:
            json.dump(config_data, f, indent=2)
        return True
    except Exception as e:
        print(f"Error writing config.json: {e}")
        return False

def read_desired_state():
    try:
        if os.path.exists(DESIRED_STATE_PATH):
            with open(DESIRED_STATE_PATH, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"Error reading desired state: {e}")
    return {"is_running": False}

def write_desired_state(is_running):
    try:
        with open(DESIRED_STATE_PATH, 'w') as f:
            json.dump({"is_running": is_running}, f, indent=2)
    except Exception as e:
        print(f"Error writing desired state: {e}")

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

def get_running_process():
    if os.path.exists(PID_PATH):
        try:
            with open(PID_PATH, 'r') as f:
                pid = int(f.read().strip())
            if is_pid_running(pid):
                return pid
        except Exception as e:
            print(f"Error checking PID file: {e}")
    return None

def terminate_pid(pid):
    if sys.platform == "win32":
        try:
            subprocess.run(f"taskkill /pid {pid} /t /f", shell=True)
        except Exception as e:
            print(f"Error terminating Windows PID {pid}: {e}")
    else:
        try:
            os.kill(pid, 15)
            for _ in range(30):
                if not is_pid_running(pid):
                    return
                time.sleep(0.1)
            os.kill(pid, 9)
        except (ProcessLookupError, OSError):
            pass

STATS_REGEX = re.compile(
    r"\[STATS\] polled=(?P<polled>[0-9,]+) \| written=(?P<written>[0-9,]+) \| db_errors=(?P<errors>[0-9]+) \| last_press=(?P<press>[0-9\.]+) \| last_vac=(?P<vac>[0-9\.]+) \| last_time=(?P<time>[0-9\.]+)"
)

def parse_and_emit_stats(line):
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
    global last_stats
    print("[SYSTEM] Musashi IV Log tailing thread started.")
    while not os.path.exists(LOG_PATH) and not stop_tail_event.is_set():
        time.sleep(0.2)
        
    try:
        with open(LOG_PATH, 'r', errors='replace') as f:
            f.seek(0, os.SEEK_END)
            while not stop_tail_event.is_set():
                pid = get_running_process()
                if pid is None:
                    socketio.emit('status_change', {'is_running': False})
                    if os.path.exists(PID_PATH):
                        try: os.remove(PID_PATH)
                        except: pass
                
                line = f.readline()
                if line:
                    clean_line = line.strip()
                    socketio.emit('log_line', {'data': clean_line})
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
    
    if write_config(current_cfg):
        return jsonify({'success': True, 'message': 'Configuration updated successfully', 'config': current_cfg})
    else:
        return jsonify({'success': False, 'message': 'Failed to save configuration'}), 500

@app.route('/api/test_db', methods=['POST'])
def test_db():
    req = request.get_json() or {}
    dsn = req.get('dsn') or read_config().get('DB_DSN')
    try:
        conn = psycopg2.connect(dsn, connect_timeout=3)
        conn.close()
        return jsonify({'success': True, 'message': 'Database connection successful!'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Database connection error: {str(e)}'})

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

@app.route('/api/status', methods=['GET'])
def get_status():
    pid = get_running_process()
    is_running = pid is not None
    return jsonify({
        'is_running': is_running,
        'pid': pid,
        'config': read_config(),
        'last_stats': last_stats
    })

@app.route('/api/start', methods=['POST'])
def start_process():
    global tail_thread, stop_tail_event, mock_api_process
    
    pid = get_running_process()
    if pid is not None:
        return jsonify({'success': False, 'message': f'Musashi IV ingestion process is already running (PID: {pid})'}), 400

    cfg = read_config()
    mock_mode = cfg.get("MOCKUP_MODE", True)
    
    # If mockup mode is ON, launch mock API server background task if 1025 is not already active
    if mock_mode:
        try:
            mock_script = os.path.join(os.path.dirname(__file__), 'mock_api_server.py')
            mock_api_process = subprocess.Popen([sys.executable, mock_script, "1025"])
            print("[SYSTEM] Started mock API server on port 1025.")
        except Exception as e:
            print(f"[SYSTEM] Mock API server start notice: {e}")

    log_file = open(LOG_PATH, 'w')
    script_path = os.path.join(os.path.dirname(__file__), 'stream_to_db.py')
    
    try:
        proc = subprocess.Popen([sys.executable, script_path], stdout=log_file, stderr=subprocess.STDOUT)
        write_desired_state(True)
        with open(PID_PATH, 'w') as f:
            f.write(str(proc.pid))
            
        stop_tail_event.clear()
        if tail_thread is None or not tail_thread.is_alive():
            tail_thread = threading.Thread(target=tail_log_file, daemon=True)
            tail_thread.start()

        socketio.emit('status_change', {'is_running': True, 'pid': proc.pid})
        return jsonify({'success': True, 'message': f'Musashi IV Ingestion started successfully (PID: {proc.pid})', 'pid': proc.pid})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Failed to start ingestion process: {str(e)}'}), 500

@app.route('/api/stop', methods=['POST'])
def stop_process():
    global mock_api_process
    pid = get_running_process()
    if pid is None:
        return jsonify({'success': False, 'message': 'No running process detected'}), 400

    write_desired_state(False)
    terminate_pid(pid)
    if os.path.exists(PID_PATH):
        try: os.remove(PID_PATH)
        except: pass
        
    if mock_api_process:
        try:
            mock_api_process.terminate()
            mock_api_process = None
        except: pass

    socketio.emit('status_change', {'is_running': False})
    return jsonify({'success': True, 'message': f'Process {pid} stopped successfully'})

@socketio.on('connect')
def handle_connect():
    pid = get_running_process()
    emit('status_change', {'is_running': pid is not None, 'pid': pid})
    if last_stats:
        emit('stats_update', last_stats)

if __name__ == '__main__':
    print("==========================================================")
    print("      Musashi IV Robot Dispenser Web GUI (Port 8083)")
    print("==========================================================")
    pid = get_running_process()
    if pid is not None:
        print(f"[SYSTEM] Detected active Musashi IV background process (PID: {pid}).")
    else:
        desired_state = read_desired_state()
        if desired_state.get('is_running', False):
            print("[SYSTEM] Device restart detected! Auto-resuming Musashi IV ingestion stream...")
            with app.test_request_context():
                start_process()
    socketio.run(app, host='0.0.0.0', port=8083, debug=False)
