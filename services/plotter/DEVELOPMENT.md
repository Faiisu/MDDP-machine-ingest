# MDDP Database Plotter: Developer Extension Guide

This guide explains the design patterns, connection testing, and extension interfaces for the multi-plot grid workspace. It walks through how to expand the plotter dashboard to support new database schemas and multi-trace services (such as Musashi II and Musashi IV).

---

## 1. Multi-Plot Grid Architecture Overview

The Database Plotter acts as a stateless visualization dashboard capable of hosting multiple charts in a dynamic grid layout:

```
                  ┌──────────────────────┐
                  │  Portal Gateway      │
                  └──────────┬───────────┘
                             │ (Port 8084)
                  ┌──────────▼───────────┐
                  │  Database Plotter    │
                  │  (Multi-Plot Grid)   │
                  └────┬────────────┬────┘
        (Query 1)      │            │      (Query 2)
  ┌────────────────────▼──┐      ┌──▼────────────────────┐
  │ [Plot 1: DAQ CH0]     │      │ [Plot 2: Musashi II]  │
  │ DSN: pg://hostA/db    │      │ DSN: pg://hostB/db    │
  └───────────────────────┘      └───────────────────────┘
```

* **Dynamic Connection Test (`/api/db/test`)**: Validates DSN strings input by the user on the fly using `psycopg2` before creating the chart.
* **Stateless Analytics API (`/api/data`)**: Accepts `dsn` as a query parameter. This allows each chart on the workspace to connect to independent host databases.
* **Layout Manager**: Changes CSS grid columns class (`col-1`, `col-2`, `col-3`) and triggers `Plotly.Plots.resize()` to auto-scale charts to their container widths.
* **Trace Drawing (`Plotly.react`)**: Efficiently repaints line charts and handles resizing without rebuilding elements.

---

## 2. Telemetry Ingestion Contract: DAQ (Current Implementation)

Currently, the service retrieves data from the DAQ ingestion table `daq_samples`:

* **Schema**:
  * `time`: `TIMESTAMPTZ` (TimescaleDB hypertable key)
  * `channel`: `SMALLINT` (corresponds to analog input index)
  * `value`: `DOUBLE PRECISION` (analog voltage level)

* **Query Logic**:
  Queries utilize indices `idx_mockup_channel_time` (channel, time DESC) to retrieve data sorted chronologically:
  ```sql
  SELECT time, value FROM daq_samples 
  WHERE channel = %s AND time >= %s AND time <= %s 
  ORDER BY time ASC;
  ```

---

## 3. How to Add a New Service (e.g., Musashi II or IV)

To support another device database table in the future, follow these four steps:

### Step 1: Design the Database Schema
Ensure the new table (e.g., `musashi_logs`) uses `time` as a primary key partition.
```sql
CREATE TABLE IF NOT EXISTS musashi_logs (
    time        TIMESTAMPTZ      NOT NULL,
    pressure    DOUBLE PRECISION NOT NULL,
    fluid_temp  DOUBLE PRECISION,
    status      VARCHAR(30)
);
SELECT create_hypertable('musashi_logs', 'time', if_not_exists => TRUE);
```

### Step 2: Add API Endpoints in `app.py`
Extend `app.py` to route queries for the new service, supporting custom DSN parsing:

```python
@app.route('/api/data/musashi')
def get_musashi_data():
    dsn_param = request.args.get('dsn')
    dsn = dsn_param if dsn_param else get_db_dsn()
    last_sec = request.args.get('last', default=60, type=float)
    
    conn = None
    try:
        conn = psycopg2.connect(dsn, connect_timeout=3)
        query = """
            SELECT time, pressure, fluid_temp 
            FROM musashi_logs 
            WHERE time >= NOW() - INTERVAL '%s second'
            ORDER BY time ASC;
        """
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute(query, (last_sec,))
            rows = cur.fetchall()
            
            times = [r['time'].isoformat() for r in rows]
            pressure = [r['pressure'] for r in rows]
            temp = [r['fluid_temp'] for r in rows]
            
        return jsonify({
            'times': times,
            'data': {
                'pressure': pressure,
                'temp': temp
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if conn:
            conn.close()
```

### Step 3: Add UI Option in Modal Form
Add option in [services/plotter/templates/index.html](file:///Users/faiisu/projects.nosync/DAQ-USB-4716/services/plotter/templates/index.html) under `<select id="modal-service-select">`:

```html
<option value="musashi_ii">Musashi II Dispenser</option>
```

### Step 4: Map Visual Layouts in `app.js`
Modify `initPlotlyChart` and `queryPlotData` in [services/plotter/static/app.js](file:///Users/faiisu/projects.nosync/DAQ-USB-4716/services/plotter/static/app.js) to dynamically configure line styling and parse endpoints:

```javascript
// Add in static/app.js
async function queryPlotData(plot) {
    let url = '';
    if (plot.service === 'musashi_ii') {
        url = `/api/data/musashi?last=${plot.timeRange}&dsn=${encodeURIComponent(plot.dsn)}`;
    }
    // Fetch and redraw using Plotly.react...
}
```
