# app.py
# See: docs/architecture/context.md
# English comments only

import os
import sys
import json
import math
import random
from datetime import datetime, timedelta, timezone
from flask import Flask, render_template, jsonify, request
import psycopg2
import psycopg2.extras

app = Flask(__name__, template_folder='templates', static_folder='static')

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from shared.config import load_config, resolve_db_dsn

# Resolve config.json path from the daq_usb4716 directory
CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', 'daq_usb4716', 'config.json')
MODE_PATH = os.path.join(os.path.dirname(__file__), '..', 'daq_usb4716', '.daq_process.mode')

def get_db_dsn():
    """
    Reads the default database DSN from config.json.
    Automatically checks the active DAQ ingestion mode. If in 'mockup' mode, 
    returns the mockup connection string; otherwise returns the production DSN.
    """
    try:
        cfg = load_config(CONFIG_PATH)
        return resolve_db_dsn(cfg, MODE_PATH)
    except Exception as e:
        print(f"Error loading DSN: {e}")
        return "postgresql://admin:admin@172.21.108.86:5432/daq_db"

@app.route('/')
def home():
    """Renders the main multi-plot workspace."""
    return render_template('index.html')

@app.route('/api/db/default')
def get_default_db():
    """Returns the default DSN configured in config.json."""
    return jsonify({'dsn': get_db_dsn()})

@app.route('/api/db/test', methods=['POST'])
def test_db_connection():
    """Validates if a given DSN string connects successfully to PostgreSQL."""
    data = request.json or {}
    dsn = data.get('dsn')
    if not dsn:
        return jsonify({'status': 'error', 'message': 'No database URL provided.'}), 400
    
    conn = None
    try:
        conn = psycopg2.connect(dsn, connect_timeout=3)
        with conn.cursor() as cur:
            cur.execute("SELECT 1;")
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
    finally:
        if conn:
            conn.close()

@app.route('/api/channels')
def get_channels():
    """Retrieves a list of available channels in the database using the specified DSN."""
    dsn_param = request.args.get('dsn')
    dsn = dsn_param if dsn_param else get_db_dsn()
    
    conn = None
    try:
        conn = psycopg2.connect(dsn, connect_timeout=3)
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT channel FROM daq_samples ORDER BY channel;")
            channels = [row[0] for row in cur.fetchall()]
        return jsonify(channels)
    except Exception as e:
        print(f"Error fetching channels: {e}")
        return jsonify([])
    finally:
        if conn:
            conn.close()

@app.route('/api/data')
def get_data():
    """
    Retrieves time-series telemetry from the database for the DAQ service.
    Query Params:
      - dsn: database DSN string (optional, falls back to config.json)
      - channel: integer (default 0)
      - last: seconds of history to fetch (default 60)
      - start: ISO datetime (optional)
      - end: ISO datetime (optional)
    """
    dsn_param = request.args.get('dsn')
    dsn = dsn_param if dsn_param else get_db_dsn()
    
    channel = request.args.get('channel', default=0, type=int)
    last_sec = request.args.get('last', default=60, type=float)
    start_str = request.args.get('start', default=None)
    end_str = request.args.get('end', default=None)

    conn = None
    try:
        conn = psycopg2.connect(dsn, connect_timeout=3)
        
        # Build query based on parameters
        if start_str and end_str:
            start_dt = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
            end_dt = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
            query = """
                SELECT time, value 
                FROM daq_samples 
                WHERE channel = %s AND time >= %s AND time <= %s 
                ORDER BY time ASC;
            """
            params = (channel, start_dt, end_dt)
        else:
            end_dt = datetime.now(timezone.utc)
            start_dt = end_dt - timedelta(seconds=last_sec)
            query = """
                SELECT time, value 
                FROM daq_samples 
                WHERE channel = %s AND time >= %s AND time <= %s 
                ORDER BY time ASC;
            """
            params = (channel, start_dt, end_dt)

        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
            
            times = [r['time'].isoformat() for r in rows]
            values = [r['value'] for r in rows]

        return jsonify({
            'times': times,
            'values': values
        })

    except Exception as e:
        print(f"Error fetching telemetry: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/data/mock')
def get_mock_data():
    """
    Generates synthetic time-series telemetry for Musashi II and IV.
    Returns dynamic curves to enable hover, slide, and zoom testing.
    """
    service = request.args.get('service', default='musashi_ii')
    last_sec = request.args.get('last', default=60, type=float)
    start_str = request.args.get('start', default=None)
    end_str = request.args.get('end', default=None)
    
    if start_str and end_str:
        start_dt = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
    else:
        end_dt = datetime.now(timezone.utc)
        start_dt = end_dt - timedelta(seconds=last_sec)
        
    duration = (end_dt - start_dt).total_seconds()
    
    # Generate around 150 points for rich resolution
    points_count = 150
    step = max(0.05, duration / points_count)
    
    times = []
    values_data = {}
    
    if service == 'musashi_ii':
        values_data['pressure'] = []
        values_data['temp'] = []
    elif service == 'musashi_iv':
        values_data['x'] = []
        values_data['y'] = []
        values_data['z'] = []
        
    t_cursor = start_dt
    t_seconds = 0.0
    
    while t_cursor <= end_dt:
        times.append(t_cursor.isoformat())
        
        if service == 'musashi_ii':
            pressure = 120.0 + 6.0 * math.sin(t_seconds * 0.1) + random.normalvariate(0, 0.4)
            temp = 24.2 + 0.005 * t_seconds + random.normalvariate(0, 0.03)
            values_data['pressure'].append(round(pressure, 2))
            values_data['temp'].append(round(temp, 2))
            
        elif service == 'musashi_iv':
            x = 40.0 + 2.5 * math.sin(t_seconds * 0.08) + random.normalvariate(0, 0.08)
            y = max(0.0, 0.05 * math.cos(t_seconds * 0.06))
            z = 1.0 + 0.01 * math.sin(t_seconds * 0.25)
            values_data['x'].append(round(x, 3))
            values_data['y'].append(round(y, 3))
            values_data['z'].append(round(z, 3))
            
        t_cursor += timedelta(seconds=step)
        t_seconds += step
        
    return jsonify({
        'times': times,
        'data': values_data
    })

@app.route('/api/data/musashi_iv')
def get_musashi_iv_db_data():
    """
    Retrieves real time-series telemetry from musashi_iv_data table.
    """
    dsn_param = request.args.get('dsn')
    dsn = dsn_param if dsn_param else get_db_dsn()
    ch_no = request.args.get('channel', default=1, type=int)
    last_sec = request.args.get('last', default=60, type=float)

    conn = None
    try:
        conn = psycopg2.connect(dsn, connect_timeout=3)
        end_dt = datetime.now(timezone.utc)
        start_dt = end_dt - timedelta(seconds=last_sec)
        query = """
            SELECT time, dis_press, dis_vacuum, dis_time 
            FROM musashi_iv_data 
            WHERE ch_no = %s AND time >= %s AND time <= %s 
            ORDER BY time ASC;
        """
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(query, (ch_no, start_dt, end_dt))
            rows = cur.fetchall()
            times = [r['time'].isoformat() for r in rows]
            pressures = [r['dis_press'] for r in rows]
            vacuums = [r['dis_vacuum'] for r in rows]
            dis_times = [r['dis_time'] for r in rows]

        return jsonify({
            'times': times,
            'data': {
                'x': pressures,
                'y': vacuums,
                'z': dis_times
            }
        })
    except Exception as e:
        # Fall back to mock curve if DB is offline
        return get_mock_data()
    finally:
        if conn:
            conn.close()

if __name__ == '__main__':
    # Served on Port 8084
    app.run(host='0.0.0.0', port=8084, debug=False)
