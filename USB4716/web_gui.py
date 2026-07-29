# web_gui.py
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
CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.json')
PID_PATH = os.path.join(os.path.dirname(__file__), '.daq_process.pid')
MODE_PATH = os.path.join(os.path.dirname(__file__), '.daq_process.mode')
DESIRED_STATE_PATH = os.path.join(os.path.dirname(__file__), '.daq_desired_state.json')
LOG_PATH = os.path.join(os.path.dirname(__file__), 'daq_pipeline.log')

# Global monitoring variables
tail_thread = None
stop_tail_event = threading.Event()
last_stats = {}

def read_config():
    """Reads configuration parameters from config.json."""
    try:
        with open(CONFIG_PATH, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error reading config.json: {e}")
        return {}

def write_config(config_data):
    """Writes configuration parameters to config.json."""
    try:
        with open(CONFIG_PATH, 'w') as f:
            json.dump(config_data, f, indent=2)
        return True
    except Exception as e:
        print(f"Error writing config.json: {e}")
        return False

def read_desired_state():
    """Reads persistent desired state metadata."""
    try:
        if os.path.exists(DESIRED_STATE_PATH):
            with open(DESIRED_STATE_PATH, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"Error reading desired state: {e}")
    return {"is_running": False, "mode": "mockup"}

def write_desired_state(is_running, mode="mockup"):
    """Writes persistent desired state metadata across system reboots."""
    try:
        with open(DESIRED_STATE_PATH, 'w') as f:
            json.dump({"is_running": is_running, "mode": mode}, f, indent=2)
    except Exception as e:
        print(f"Error writing desired state: {e}")

# Cross-platform utility to check if a process is still active on the host OS
def is_pid_running(pid):
    if sys.platform == "win32":
        try:
            # Query tasklist on Windows
            output = subprocess.check_output(f'tasklist /fi "PID eq {pid}"', shell=True)
            return str(pid) in str(output)
        except Exception:
            return False
    else:
        try:
            # Query signal 0 (null signal) on POSIX
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
            print(f"Error checking active PID file: {e}")
    return None, None

# Terminate process by PID cross-platform
def terminate_pid(pid):
    if sys.platform == "win32":
        try:
            subprocess.run(f"taskkill /pid {pid} /t /f", shell=True)
        except Exception as e:
            print(f"Error terminating Windows PID {pid}: {e}")
    else:
        try:
            os.kill(pid, 15) # SIGTERM (graceful exit)
            # Wait up to 3 seconds for exit, force kill if stuck
            for _ in range(30):
                if not is_pid_running(pid):
                    return
                time.sleep(0.1)
            os.kill(pid, 9) # SIGKILL
        except ProcessLookupError:
            pass
        except OSError as e:
            print(f"Error terminating Unix PID {pid}: {e}")

# Regex to extract statistics from the log file
# E.g.: [STATS] polled=1,024 | written=1,024 | dropped_batches=0 (0.0%) | db_errors=0 | queue=0/200
STATS_REGEX = re.compile(
    r"\[STATS\] polled=(?P<polled>[0-9,]+) \| written=(?P<written>[0-9,]+) \| dropped_batches=(?P<dropped>[0-9]+) \((?P<loss_pct>[0-9\.]+)%\) \| db_errors=(?P<errors>[0-9]+) \| queue=(?P<qsize>[0-9]+)/(?P<qmax>[0-9]+)"
)

def parse_and_emit_stats(line):
    """Parses stats from a line and updates global caches."""
    global last_stats
    match = STATS_REGEX.search(line)
    if match:
        last_stats = {
            'polled': match.group('polled'),
            'written': match.group('written'),
            'dropped': match.group('dropped'),
            'loss_pct': match.group('loss_pct'),
            'errors': match.group('errors'),
            'queue_util': f"{match.group('qsize')}/{match.group('qmax')}"
        }
        socketio.emit('stats_update', last_stats)

def tail_log_file():
    """Background loop tailing the physical log file to feed sockets."""
    global last_stats
    print("[SYSTEM] Log tailing thread started.")
    
    # Wait until log file is created
    while not os.path.exists(LOG_PATH) and not stop_tail_event.is_set():
        time.sleep(0.2)
        
    try:
        with open(LOG_PATH, 'r', errors='replace') as f:
            # Start tailing from the end of the file
            f.seek(0, os.SEEK_END)
            
            while not stop_tail_event.is_set():
                pid, _ = get_running_process()
                if pid is None:
                    # DAQ process stopped; close tailing thread and notify client
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
                # Broadcast log line to connected sockets
                socketio.emit('log_update', {'log': decoded_line})
                parse_and_emit_stats(decoded_line)
                
    except Exception as e:
        print(f"Error tailing log file: {e}")
    finally:
        print("[SYSTEM] Log tailing thread finished.")

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
        print(f"Error reading historical logs: {e}")
        return []

def scan_host_usb_devices():
    """Scans host PC for connected Advantech DAQ cards, USB-serial ports, and USB devices."""
    detected = []

    # 1. Advantech DAQNavi SDK Enumeration
    try:
        sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir)))
        from Automation.BDaq import WaveformAiCtrl
        installed_devices = WaveformAiCtrl.getInstalledDevices()
        for dev in installed_devices:
            dev_desc = getattr(dev, 'Description', str(dev))
            board_num = getattr(dev, 'BoardNumber', 0)
            detected.append({
                'id': dev_desc,
                'name': f"Advantech {dev_desc}",
                'type': 'Advantech DAQ Card',
                'port': f"BID#{board_num}",
                'vendor': 'Advantech',
                'is_daq': True
            })
    except Exception as e:
        print(f"[SCAN] Advantech SDK scan note: {e}")

    # 2. USB Serial & COM Ports via PySerial
    try:
        import serial.tools.list_ports
        ports = serial.tools.list_ports.comports()
        for p in ports:
            desc = p.description if p.description else p.device
            mfg = p.manufacturer if hasattr(p, 'manufacturer') and p.manufacturer else 'USB Serial'
            detected.append({
                'id': p.device,
                'name': f"{p.device} ({desc})",
                'type': 'USB Serial Port',
                'port': p.device,
                'vendor': mfg,
                'hwid': p.hwid if hasattr(p, 'hwid') else '',
                'is_daq': False
            })
    except Exception as e:
        print(f"[SCAN] Serial ports scan note: {e}")

    # 3. Default Hardware & Simulation Fallbacks
    detected.append({
        'id': 'USB-4716,BID#0',
        'name': 'USB-4716 Default Board (BID#0)',
        'type': 'Advantech DAQ Default',
        'port': 'BID#0',
        'vendor': 'Advantech',
        'is_daq': True
    })

    detected.append({
        'id': 'USB-4716 (Mockup Mode)',
        'name': 'USB-4716 Virtual Hardware (Driverless Simulation)',
        'type': 'Mockup / Driverless',
        'port': 'Virtual',
        'vendor': 'Software Mock',
        'is_daq': True
    })

    # Deduplicate by 'id' while retaining order
    seen = set()
    unique_detected = []
    for d in detected:
        if d['id'] not in seen:
            seen.add(d['id'])
            unique_detected.append(d)

    return unique_detected

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/config', methods=['GET'])
def get_config():
    return jsonify(read_config())

@app.route('/api/config', methods=['POST'])
def save_config():
    config_data = request.json
    if write_config(config_data):
        return jsonify({'status': 'success'})
    return jsonify({'status': 'error', 'message': 'Failed to save configuration.'}), 500

@app.route('/api/test_db', methods=['POST'])
def test_db():
    req = request.get_json() or {}
    cfg = read_config()
    dest = req.get('DESTINATION') or req.get('destination') or cfg.get('DESTINATION', 'postgresql')

    if dest == 'influxdb':
        url = req.get('INFLUX_URL') or cfg.get('INFLUX_URL', 'http://localhost:8086')
        token = req.get('INFLUX_TOKEN') or cfg.get('INFLUX_TOKEN', '')
        org = req.get('INFLUX_ORG') or cfg.get('INFLUX_ORG', 'mddp')
        bucket = req.get('INFLUX_BUCKET') or cfg.get('INFLUX_BUCKET', 'daq_telemetry')

        target_url = f"{url.rstrip('/')}/health"
        headers = {"User-Agent": "USB4716-TestClient"}
        if token:
            headers["Authorization"] = f"Token {token}"

        try:
            import urllib.request
            req_obj = urllib.request.Request(target_url, headers=headers, method="GET")
            with urllib.request.urlopen(req_obj, timeout=4.0) as resp:
                if resp.status in (200, 204):
                    return jsonify({'success': True, 'message': f'InfluxDB server at {url} is HEALTHY! (Org: {org}, Bucket: {bucket})'})
                else:
                    return jsonify({'success': False, 'message': f'InfluxDB returned HTTP status {resp.status}'})
        except Exception as e:
            return jsonify({'success': False, 'message': f'InfluxDB connection error: {str(e)}'})
    elif dest == 'mqtt':
        return jsonify({'success': True, 'message': 'MQTT Broker target configured.'})
    else:
        dsn = req.get('DB_DSN') or cfg.get('DB_DSN')
        if not dsn:
            host = req.get('DB_HOST') or cfg.get('DB_HOST', 'localhost')
            port = req.get('DB_PORT') or cfg.get('DB_PORT', 5432)
            user = req.get('DB_USER') or cfg.get('DB_USER', 'admin')
            password = req.get('DB_PASSWORD') or cfg.get('DB_PASSWORD', 'admin')
            dbname = req.get('DB_NAME') or cfg.get('DB_NAME', 'daq_db')
            dsn = f"postgresql://{user}:{password}@{host}:{port}/{dbname}"

        try:
            import psycopg2
            conn = psycopg2.connect(dsn, connect_timeout=3)
            conn.close()
            return jsonify({'success': True, 'message': 'PostgreSQL/TimescaleDB connection successful!'})
        except Exception as e:
            return jsonify({'success': False, 'message': f'PostgreSQL connection error: {str(e)}'})

@app.route('/api/status', methods=['GET'])
def get_status():
    pid, mode = get_running_process()
    dest = read_config().get('DESTINATION', 'database')
    return jsonify({
        'is_running': pid is not None,
        'run_mode': mode or 'mockup',
        'destination': dest
    })

@app.route('/api/scan_usb', methods=['GET'])
def api_scan_usb():
    """Returns JSON list of detected USB and DAQ hardware devices on the host PC."""
    devices = scan_host_usb_devices()
    return jsonify({
        'status': 'success',
        'count': len(devices),
        'devices': devices
    })


@socketio.on('connect')
def handle_connect():
    """Fires when browser client opens or refreshes the page."""
    pid, mode = get_running_process()
    is_active = pid is not None
    dest = read_config().get('DESTINATION', 'database')
    
    # 1. Update client running status immediately
    emit('status_change', {'is_running': is_active, 'mode': mode or 'mockup', 'destination': dest})
    
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

@socketio.on('start_daq')
def handle_start(data):
    """Spawns DAQ script in a detached process."""
    pid, mode = get_running_process()
    if pid is not None:
        emit('log_update', {'log': '[SYSTEM] Warning: Ingestion process is already running.'})
        return
        
    run_mode = data.get('mode', 'mockup')
    write_desired_state(True, run_mode)
    dest = read_config().get('DESTINATION', 'database')
    script_name = "mockup_stream_to_db.py" if run_mode == "mockup" else "stream_to_db.py"
    script_path = os.path.join(os.path.dirname(__file__), script_name)
    
    try:
        # Clear/truncate old log file session
        with open(LOG_PATH, 'w') as f:
            f.write(f"[SYSTEM] Log session initialized for mode={run_mode.upper()} destination={dest.upper()}\n")
            
        # Open log file to pipe subprocess output
        log_file = open(LOG_PATH, 'a')
        
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        
        # Spawn process completely detached using shell redirects
        # close_fds: True on POSIX to detach FDs; must be False on
        # Windows when stdout/stderr are redirected (Python limitation).
        popen_kwargs = dict(
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=env,
        )
        if sys.platform != "win32":
            popen_kwargs["close_fds"] = True
        else:
            popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        proc = subprocess.Popen(
            [sys.executable, script_path],
            **popen_kwargs,
        )
        
        # Close file handle in parent process
        log_file.close()
        
        # Persist PID & Mode metadata
        with open(PID_PATH, 'w') as f:
            f.write(str(proc.pid))
        with open(MODE_PATH, 'w') as f:
            f.write(run_mode)
            
        # Update sockets immediately
        socketio.emit('status_change', {'is_running': True, 'mode': run_mode, 'destination': dest})
        socketio.emit('log_update', {'log': f'[SYSTEM] Spawning process (PID: {proc.pid}) target={dest.upper()}'})
        
        # Start log tailer thread
        start_tailing()
        
    except Exception as e:
        socketio.emit('log_update', {'log': f'[SYSTEM] Failed to spawn process: {e}'})

@socketio.on('stop_daq')
def handle_stop():
    """Stops the detached process by its recorded PID."""
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
    socketio.emit('log_update', {'log': f'[SYSTEM] Terminating process (PID: {pid})...'})
    
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
    socketio.emit('log_update', {'log': '[SYSTEM] Ingestion process terminated.'})

# Initial recovery check on Web GUI startup
pid, mode = get_running_process()
if pid is not None:
    print(f"[SYSTEM] Detected active background process running (PID: {pid}). Re-attaching...")
    start_tailing()
else:
    desired_state = read_desired_state()
    if desired_state.get('is_running', False):
        saved_mode = desired_state.get('mode', 'mockup')
        print(f"[SYSTEM] Device restart detected! Auto-resuming DAQ ingestion in MODE={saved_mode.upper()}...")
        handle_start({'mode': saved_mode})

if __name__ == '__main__':
    # Served on Port 8081
    socketio.run(app, host='0.0.0.0', port=8081, debug=False)
