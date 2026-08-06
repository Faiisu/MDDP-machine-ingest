import os
import sys
import json
import subprocess
import urllib.request
import urllib.parse
from flask import Flask, render_template, jsonify, request

app = Flask(__name__, template_folder='templates', static_folder='static')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, '..', '..'))
CONFIG_PATH = os.path.join(BASE_DIR, 'influxdb_config.json')
COMPOSE_FILE = os.path.join(PROJECT_ROOT, 'docker-compose.influxdb.yml')
ENV_FILE = os.path.join(PROJECT_ROOT, '.env.influxdb')

def read_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "INFLUX_URL": "http://localhost:8086",
        "INFLUX_ORG": "mddp",
        "INFLUX_BUCKET": "daq_telemetry",
        "INFLUX_MEASUREMENT": "daq_telemetry",
        "INFLUX_USERNAME": "admin",
        "INFLUX_PASSWORD": "admin1234",
        "INFLUX_TOKEN": "",
        "RETENTION_ENABLED": False,
        "RETENTION_DAYS": 30,
        "RETENTION_HOURS": 0,
        "RETENTION_MINUTES": 0,
        "RETENTION_SECONDS": 0
    }

def write_config(data):
    try:
        with open(CONFIG_PATH, 'w') as f:
            json.dump(data, f, indent=2)
        write_env_file(data)
        return True
    except Exception as e:
        print(f"[ERROR] Error writing config: {e}")
        return False

def write_env_file(data):
    try:
        lines = [
            f"INFLUX_USERNAME={data.get('INFLUX_USERNAME', 'admin')}",
            f"INFLUX_PASSWORD={data.get('INFLUX_PASSWORD', 'admin1234')}",
            f"INFLUX_ORG={data.get('INFLUX_ORG', 'mddp')}",
            f"INFLUX_BUCKET={data.get('INFLUX_BUCKET', 'daq_telemetry')}",
        ]
        with open(ENV_FILE, 'w') as f:
            f.write('\n'.join(lines) + '\n')
    except Exception as e:
        print(f"[ERROR] Error writing env file: {e}")

def run_docker_compose(cmd_list):
    try:
        cmd = ['docker', 'compose', '--env-file', ENV_FILE, '-f', COMPOSE_FILE] + cmd_list
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return res.returncode == 0, res.stdout + res.stderr
    except Exception as e:
        return False, str(e)

def auto_discover_token():
    """Attempts to discover or create operator token from mddp-influxdb docker container."""
    try:
        cmd = ['docker', 'exec', 'mddp-influxdb', 'influx', 'auth', 'list', '--json']
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            auth_list = json.loads(res.stdout)
            if isinstance(auth_list, list):
                for auth in auth_list:
                    tok = auth.get('token')
                    if tok:
                        return tok
        # If no visible token found, attempt to create an all-access token
        cfg = read_config()
        org = cfg.get('INFLUX_ORG', 'PTT')
        create_cmd = ['docker', 'exec', 'mddp-influxdb', 'influx', 'auth', 'create', '--all-access', '--org', org, '--json']
        res_create = subprocess.run(create_cmd, capture_output=True, text=True, timeout=10)
        if res_create.returncode == 0:
            auth_obj = json.loads(res_create.stdout)
            if isinstance(auth_obj, dict) and auth_obj.get('token'):
                return auth_obj.get('token')
    except Exception as e:
        print(f"[DEBUG] Token discovery notice: {e}")
    return None

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/config', methods=['GET'])
def get_config():
    cfg = read_config()
    # Try discovering token if not present in config
    if not cfg.get('INFLUX_TOKEN'):
        tok = auto_discover_token()
        if tok:
            cfg['INFLUX_TOKEN'] = tok
            write_config(cfg)
    return jsonify(cfg)

@app.route('/api/config', methods=['POST'])
def save_config_route():
    data = request.get_json() or {}
    cfg = read_config()
    cfg.update(data)
    if write_config(cfg):
        return jsonify({'status': 'success', 'config': cfg})
    return jsonify({'status': 'error', 'message': 'Failed to save config.'}), 500

@app.route('/api/status', methods=['GET'])
def get_status():
    cfg = read_config()
    container_status = 'stopped'
    healthy = False
    
    # Check Docker container status
    try:
        res = subprocess.run(
            ['docker', 'inspect', '--format', '{{.State.Status}}', 'mddp-influxdb'],
            capture_output=True, text=True, timeout=5
        )
        if res.returncode == 0:
            container_status = res.stdout.strip()
    except Exception:
        container_status = 'not_installed_or_docker_offline'

    # Check InfluxDB HTTP health
    url = cfg.get('INFLUX_URL', 'http://localhost:8086').rstrip('/')
    health_url = f"{url}/health"
    try:
        req = urllib.request.Request(health_url, headers={'User-Agent': 'InfluxManager'}, method='GET')
        with urllib.request.urlopen(req, timeout=3) as resp:
            if resp.status in (200, 204):
                healthy = True
    except Exception:
        healthy = False

    # Auto discover token if missing
    token = cfg.get('INFLUX_TOKEN', '')
    if healthy and not token:
        discovered_tok = auto_discover_token()
        if discovered_tok:
            token = discovered_tok
            cfg['INFLUX_TOKEN'] = token
            write_config(cfg)

    return jsonify({
        'container_status': container_status,
        'is_healthy': healthy,
        'influx_url': url,
        'has_token': bool(token),
        'token': token
    })

@app.route('/api/start', methods=['POST'])
def start_influx():
    cfg = read_config()
    write_env_file(cfg)
    ok, output = run_docker_compose(['up', '-d'])
    if ok:
        # Try retrieving token after brief wait
        import time
        time.sleep(2)
        tok = auto_discover_token()
        if tok:
            cfg['INFLUX_TOKEN'] = tok
            write_config(cfg)
        return jsonify({'status': 'success', 'output': output, 'token': tok})
    return jsonify({'status': 'error', 'message': output}), 500

@app.route('/api/stop', methods=['POST'])
def stop_influx():
    ok, output = run_docker_compose(['stop'])
    if ok:
        return jsonify({'status': 'success', 'output': output})
    return jsonify({'status': 'error', 'message': output}), 500

@app.route('/api/retention', methods=['POST'])
def set_retention():
    data = request.get_json() or {}
    enabled = data.get('enabled', False)
    days = int(data.get('days', 0))
    hours = int(data.get('hours', 0))
    minutes = int(data.get('minutes', 0))
    seconds = int(data.get('seconds', 0))

    total_sec = (days * 86400) + (hours * 3600) + (minutes * 60) + seconds

    cfg = read_config()
    cfg['RETENTION_ENABLED'] = enabled
    cfg['RETENTION_DAYS'] = days
    cfg['RETENTION_HOURS'] = hours
    cfg['RETENTION_MINUTES'] = minutes
    cfg['RETENTION_SECONDS'] = seconds
    cfg['RETENTION_TOTAL_SEC'] = total_sec
    write_config(cfg)

    url = cfg.get('INFLUX_URL', 'http://localhost:8086').rstrip('/')
    token = cfg.get('INFLUX_TOKEN', '')
    org = cfg.get('INFLUX_ORG', 'mddp')
    bucket_name = cfg.get('INFLUX_BUCKET', 'daq_telemetry')

    if not token:
        # try discovering
        token = auto_discover_token() or ""

    if not token:
        return jsonify({'status': 'error', 'message': 'API Token is required to set retention policy.'}), 400

    headers = {
        'Authorization': f'Token {token}',
        'Content-Type': 'application/json'
    }

    try:
        # Step 1: Query buckets to get bucket ID
        query_url = f"{url}/api/v2/buckets?name={urllib.parse.quote(bucket_name)}&org={urllib.parse.quote(org)}"
        req = urllib.request.Request(query_url, headers=headers, method='GET')
        with urllib.request.urlopen(req, timeout=5) as resp:
            res_data = json.loads(resp.read())
            buckets = res_data.get('buckets', [])
            if not buckets:
                return jsonify({'status': 'error', 'message': f'Bucket "{bucket_name}" not found in InfluxDB.'}), 440
            bucket_id = buckets[0]['id']

        # Step 2: PATCH retention rule
        patch_url = f"{url}/api/v2/buckets/{bucket_id}"
        patch_body = {
            'retentionRules': [
                {'type': 'expire', 'everySeconds': total_sec if enabled else 0}
            ]
        }
        patch_req = urllib.request.Request(
            patch_url,
            data=json.dumps(patch_body).encode('utf-8'),
            headers=headers,
            method='PATCH'
        )
        with urllib.request.urlopen(patch_req, timeout=5) as resp:
            updated_bucket = json.loads(resp.read())
            return jsonify({
                'status': 'success',
                'message': f'Retention policy updated successfully! (Total seconds: {total_sec if enabled else "Infinite"})',
                'bucket': updated_bucket
            })

    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Failed to set retention policy: {str(e)}'}), 500

@app.route('/api/sync_daq', methods=['POST'])
def sync_daq():
    cfg = read_config()
    daq_config_url = 'http://localhost:8081/api/config'
    
    try:
        # 1. Fetch current DAQ config
        req_get = urllib.request.Request(daq_config_url, method='GET')
        with urllib.request.urlopen(req_get, timeout=3) as resp:
            daq_cfg = json.loads(resp.read())

        # 2. Update InfluxDB connection parameters
        daq_cfg['INFLUX_URL'] = cfg.get('INFLUX_URL', 'http://localhost:8086')
        daq_cfg['INFLUX_ORG'] = cfg.get('INFLUX_ORG', 'mddp')
        daq_cfg['INFLUX_BUCKET'] = cfg.get('INFLUX_BUCKET', 'daq_telemetry')
        daq_cfg['INFLUX_MEASUREMENT'] = cfg.get('INFLUX_MEASUREMENT', 'daq_telemetry')
        daq_cfg['INFLUX_TOKEN'] = cfg.get('INFLUX_TOKEN', '')

        # 3. Post back to DAQ config
        data_bytes = json.dumps(daq_cfg).encode('utf-8')
        req_post = urllib.request.Request(
            daq_config_url,
            data=data_bytes,
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        with urllib.request.urlopen(req_post, timeout=3) as resp:
            return jsonify({'status': 'success', 'message': 'Synced InfluxDB credentials to DAQ Service (Port 8081)'})

    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Failed to sync with DAQ service: {str(e)}'}), 500

@app.route('/api/logs', methods=['GET'])
def get_logs():
    try:
        res = subprocess.run(
            ['docker', 'logs', '--tail', '50', 'mddp-influxdb'],
            capture_output=True, text=True, timeout=5
        )
        return jsonify({'status': 'success', 'logs': res.stdout + res.stderr})
    except Exception as e:
        return jsonify({'status': 'error', 'logs': f'Error fetching logs: {str(e)}'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', os.environ.get('INFLUXDB_MANAGER_PORT', 18085)))
    print(f"[SYSTEM] Starting InfluxDB Management Service on Port {port}...")
    app.run(host='0.0.0.0', port=port, debug=False)
