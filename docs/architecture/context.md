# System Context Diagram

```mermaid
graph TB
  subgraph HW [Hardware Layer]
    DAQ["🔌 USB-4716 DAQ Card"]
  end
  subgraph APP [Streaming Application]
    Pipeline["🐍 Python Pipeline (stream_to_db.py)"]
  end
  subgraph DB [Database Layer]
    TimescaleDB[("🗄️ TimescaleDB / Postgres")]
  end
  subgraph UI [Visualization Layer]
    Plotter["📈 Plotly.js Visualizer (services/plotter/app.py)"]
  end

  DAQ -->|Analog Signals| DAQ
  DAQ -->|Advantech DAQNavi SDK| Pipeline
  Pipeline -->|SQL batch INSERT| TimescaleDB
  TimescaleDB -->|SQL SELECT| Plotter
```

**What this shows**: The physical DAQ hardware card (USB-4716) feeds analog signals which are read via the Advantech DAQNavi SDK by the Python streaming pipeline process (`stream_to_db.py`). The pipeline batch inserts rows into TimescaleDB, which is then queried by the visualizer service (`services/plotter/app.py`) to display live Plotly.js charts.
