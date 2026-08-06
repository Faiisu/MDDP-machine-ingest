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

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from services.daq_usb4716.rate_control import normalize_channel_sample_rates
except ImportError:
    from rate_control import normalize_channel_sample_rates

app = Flask(__name__, template_folder='templates', static_folder='static')
socketio = SocketIO(app, cors_allowed_origins="*")

# State files to persist process metadata across restarts
CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.json')
PID_PATH = os.path.join(os.path.dirname(__file__), '.daq_process.pid')
MODE_PATH = os.path.join(os.path.dirname(__file__), '.daq_process.mode')
DESIRED_STATE_PATH = os.path.join(os.path.dirname(__file__), '.daq_desired_state.json')
LOG_PATH = os.path.join(os.path.dirname(__file__), 'daq_pipeline.log')

# DAQNavi exposes DIO input as byte-sized ports.  The USB-4716 has one
# 8-bit digital-input port (DI0..DI7); the console must not turn the device's
# five physical terminal connectors into five logical DI ports.
MAX_DI_PORTS = 1

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


def normalize_config(config_data):
    """Validate and normalize values that affect hardware acquisition."""
    if not isinstance(config_data, dict):
        raise ValueError('Configuration payload must be a JSON object.')

    normalized = dict(config_data)

    def as_int(key, default):
        value = normalized.get(key, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be an integer.")

    di_start_port = as_int('DI_START_PORT', 0)
    di_port_count = as_int('DI_PORT_COUNT', 1)
    di_channel_offset = as_int('DI_CHANNEL_OFFSET', 100)
    hardware_clock_rate = as_int('CLOCK_RATE', 1000)
    if hardware_clock_rate < 1:
        raise ValueError('CLOCK_RATE must be greater than zero.')

    channel_sample_rates = normalize_channel_sample_rates(
        normalized.get('CHANNEL_SAMPLE_RATES', {}),
        hardware_rate=hardware_clock_rate,
        section_length=normalized.get('SECTION_LENGTH', 500),
    )

    def as_bool(value, default=False):
        if value is None:
            return default
        if isinstance(value, str):
            return value.strip().lower() in {'1', 'true', 'yes', 'on'}
        return bool(value)

    raw_di_channels = normalized.get('DI_CHANNELS')
    if raw_di_channels is None:
        enable_di = as_bool(normalized.get('ENABLE_DI', False))
        di_channels = [bool(enable_di)] * 8
    elif isinstance(raw_di_channels, dict):
        di_channels = [as_bool(raw_di_channels.get(str(bit), False)) for bit in range(8)]
    elif isinstance(raw_di_channels, list) and len(raw_di_channels) == 8:
        di_channels = [as_bool(value) for value in raw_di_channels]
    else:
        raise ValueError('DI_CHANNELS must contain exactly 8 channel selections.')

    # ENABLE_DI is retained as a backwards-compatible internal flag.  The
    # selected channels are the source of truth for the new frontend.
    enable_di = any(di_channels)

    if di_start_port < 0 or di_start_port >= MAX_DI_PORTS:
        raise ValueError(f'DI_START_PORT must be between 0 and {MAX_DI_PORTS - 1}.')
    if di_port_count < 1 or di_start_port + di_port_count > MAX_DI_PORTS:
        raise ValueError(
            f'DI_PORT_COUNT must be between 1 and {MAX_DI_PORTS - di_start_port} '
            f'for start port {di_start_port}.'
        )
    if di_channel_offset < 0:
        raise ValueError('DI_CHANNEL_OFFSET must be zero or greater.')

    normalized['DI_START_PORT'] = di_start_port
    normalized['DI_PORT_COUNT'] = di_port_count
    normalized['DI_END_PORT'] = di_start_port + di_port_count - 1
    normalized['DI_CHANNEL_OFFSET'] = di_channel_offset
    normalized['DI_CHANNELS'] = di_channels
    normalized['CLOCK_RATE'] = hardware_clock_rate
    normalized['CHANNEL_SAMPLE_RATES'] = channel_sample_rates
    normalized['ENABLE_DI'] = enable_di
    return normalized

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
    config_data = request.get_json(silent=True)
    try:
        config_data = normalize_config(config_data)
    except ValueError as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

    if write_config(config_data):
        return jsonify({'status': 'success', 'config': config_data})
    return jsonify({'status': 'error', 'message': 'Failed to save configuration.'}), 500

@app.route('/api/test_db', methods=['POST'])
def test_db():
    req = request.get_json(silent=True) or {}
    if not isinstance(req, dict):
        return jsonify({'success': False, 'message': 'Connection test payload must be a JSON object.'}), 400

    cfg = read_config()

    def setting(key, default=None):
        """Use submitted form values when present, including an intentional blank."""
        return req[key] if key in req else cfg.get(key, default)

    if 'DESTINATION' in req:
        raw_dest = req['DESTINATION']
    elif 'destination' in req:
        raw_dest = req['destination']
    else:
        raw_dest = cfg.get('DESTINATION', 'postgresql')
    dest = str(raw_dest or 'postgresql').strip().lower()
    if dest == 'database':
        dest = 'postgresql'
    if dest not in {'postgresql', 'influxdb', 'mqtt'}:
        return jsonify({'success': False, 'message': f'Unsupported destination: {dest}'}), 400

    if dest == 'influxdb':
        url = str(setting('INFLUX_URL', 'http://localhost:8086') or '').strip().rstrip('/')
        token = str(setting('INFLUX_TOKEN', '') or '').strip()
        if not url:
            return jsonify({'success': False, 'message': 'InfluxDB server URL is required.'})

        target_url = f"{url}/health"
        headers = {"User-Agent": "USB4716-TestClient"}
        if token:
            headers["Authorization"] = f"Token {token}"

        try:
            import urllib.request
            req_obj = urllib.request.Request(target_url, headers=headers, method="GET")
            with urllib.request.urlopen(req_obj, timeout=4.0) as resp:
                if resp.status in (200, 204):
                    auth_note = ' Authentication was included.' if token else ' No API token was provided, so only server health was checked.'
                    return jsonify({'success': True, 'message': f'InfluxDB server at {url} is healthy.{auth_note}'})
                return jsonify({'success': False, 'message': f'InfluxDB returned HTTP status {resp.status}'})
        except Exception as e:
            return jsonify({'success': False, 'message': f'InfluxDB connection error: {str(e)}'})

    if dest == 'mqtt':
        broker = str(setting('MQTT_BROKER', 'localhost') or '').strip()
        if not broker:
            return jsonify({'success': False, 'message': 'MQTT broker host is required.'})

        try:
            port = int(setting('MQTT_PORT', 1883))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'message': 'MQTT broker port must be an integer.'})
        if not 1 <= port <= 65535:
            return jsonify({'success': False, 'message': 'MQTT broker port must be between 1 and 65535.'})

        client = None
        try:
            import paho.mqtt.client as mqtt

            try:
                client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='daq_usb4716_connection_test')
            except (AttributeError, TypeError):
                client = mqtt.Client(client_id='daq_usb4716_connection_test')

            username = str(setting('MQTT_USERNAME', '') or '').strip()
            password = setting('MQTT_PASSWORD', '') or ''
            if username:
                client.username_pw_set(username, password)

            tls_value = setting('MQTT_TLS_ENABLED', False)
            tls_enabled = (
                tls_value if isinstance(tls_value, bool)
                else str(tls_value).strip().lower() in {'1', 'true', 'yes', 'on'}
            )
            if tls_enabled:
                import os
                ca_certs = setting('MQTT_CA_CERTS', '') or None
                certfile = setting('MQTT_CLIENT_CERT', '') or None
                keyfile = setting('MQTT_CLIENT_KEY', '') or None
                client.tls_set(
                    ca_certs=ca_certs if ca_certs and os.path.exists(ca_certs) else None,
                    certfile=certfile if certfile and os.path.exists(certfile) else None,
                    keyfile=keyfile if keyfile and os.path.exists(keyfile) else None,
                )

            connected = threading.Event()
            connection_error = []

            def on_connect(_client, _userdata, _flags, rc, _properties=None):
                rc_value = getattr(rc, 'value', rc)
                if rc_value == 0:
                    connected.set()
                else:
                    connection_error.append(f'broker returned code {rc_value}')
                    connected.set()

            client.on_connect = on_connect
            client.connect(broker, port, keepalive=10)
            client.loop_start()
            connected.wait(timeout=3.0)

            if connection_error:
                return jsonify({'success': False, 'message': f'MQTT connection failed: {connection_error[0]}'})
            if not connected.is_set():
                return jsonify({'success': False, 'message': f'MQTT connection timed out at {broker}:{port}.'})
            return jsonify({'success': True, 'message': f'MQTT broker connection successful at {broker}:{port}.'})
        except ImportError:
            return jsonify({'success': False, 'message': 'paho-mqtt is not installed. Install the DAQ service requirements.'})
        except Exception as e:
            return jsonify({'success': False, 'message': f'MQTT connection error: {str(e)}'})
        finally:
            try:
                if client:
                    client.disconnect()
                    client.loop_stop()
            except Exception:
                pass

    dsn = str(setting('DB_DSN', '') or '').strip()
    if not dsn:
        host = str(setting('DB_HOST', 'localhost') or '').strip()
        port = setting('DB_PORT', 5432)
        user = str(setting('DB_USER', 'admin') or '').strip()
        password = setting('DB_PASSWORD', 'admin') or ''
        dbname = str(setting('DB_NAME', 'daq_db') or '').strip()
        if not host or not user or not dbname:
            return jsonify({'success': False, 'message': 'Database host, username, and database name are required.'})
        dsn = f"postgresql://{user}:{password}@{host}:{port}/{dbname}"

    try:
        import psycopg2
        conn = psycopg2.connect(dsn, connect_timeout=3)
        try:
            with conn.cursor() as cursor:
                cursor.execute('SELECT 1')
        finally:
            conn.close()
        return jsonify({'success': True, 'message': 'PostgreSQL/TimescaleDB connection and query test successful.'})
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
    cfg = read_config()
    desired_state = read_desired_state()
    auto_start_enabled = cfg.get('AUTO_START_ON_STARTUP', True)
    is_desired_running = desired_state.get('is_running', False)
    
    if auto_start_enabled or is_desired_running:
        target_mode = cfg.get('AUTO_START_MODE') or desired_state.get('mode', 'mockup')
        print(f"[SYSTEM] Startup config AUTO_START_ON_STARTUP is enabled. Auto-starting DAQ ingestion in MODE={target_mode.upper()}...")
        handle_start({'mode': target_mode})
    else:
        print("[SYSTEM] Startup config AUTO_START_ON_STARTUP is disabled. Awaiting manual start trigger.")

if __name__ == '__main__':
    # Served on Port 8081
    socketio.run(app, host='0.0.0.0', port=8081, debug=False)
