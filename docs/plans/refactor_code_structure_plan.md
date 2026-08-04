# Implementation Plan - Project Refactoring & Folder Management

Refactor the MDDP Ingestion Control Suite code structure and folder management to improve project maintainability, enforce consistent naming conventions, eliminate leftover/junk directories, and introduce shared core modules.

## Goal Description
The repository currently contains 5 separate sub-applications (`USB4716`, `musashi_II`, `mushashi_IV`, `plot_service`, `portal`) with inconsistent casing, directory typos (`mushashi_IV` vs `musashi_II`), an empty folder mistakenly named `db_setup.sql/`, a redundant empty `web_gui/` folder, a nested `.venv` inside `musashi_II/`, and hardcoded cross-directory path dependencies (e.g. `plot_service/app.py` reading `USB4716/config.json`).

This refactoring will:
1. **Unify Microservices**: Move sub-apps under a clean `services/` directory with consistent `snake_case` naming (`daq_usb4716`, `musashi_ii`, `musashi_iv`, `plotter`, `portal`).
2. **Fix Folder Typos & Clean Junk**:
   - Fix `mushashi_IV` -> `services/musashi_iv`.
   - Remove empty `db_setup.sql/` directory and replace with proper `scripts/sql/db_setup.sql`.
   - Remove redundant `web_gui/` empty directory and nested `musashi_II/.venv`.
3. **Extract Shared Python Modules (`shared/`)**:
   - `shared/config.py`: Centralized configuration and DSN loader.
   - `shared/db.py`: Database connection helpers and schema initialization.
   - `shared/process_manager.py`: Standardized daemon process management (PID files, desired state JSON, logs).
4. **Update Deployment Runners & Scripts**: Update `deploy/linux/run.sh`, `stop.sh`, `deploy/windows/run.bat`, `stop.bat`, `setup_systemd.sh`, `setup_task_scheduler.ps1`, `watchdog.ps1`, and systemd service definitions.
5. **Update Documentation**: Update `README.md`, `DEPLOY_LINUX.md`, and `DEPLOY_WINDOWS.md` links and paths.

---

## User Review Required

> [!IMPORTANT]
> **Directory Restructuring & Naming**:
> Service paths will change from top-level heterogeneous names to unified paths under `services/`:
> - `USB4716/` $\rightarrow$ `services/daq_usb4716/`
> - `musashi_II/` $\rightarrow$ `services/musashi_ii/`
> - `mushashi_IV/` $\rightarrow$ `services/musashi_iv/` (fixing directory typo)
> - `plot_service/` $\rightarrow$ `services/plotter/`
> - `portal/` $\rightarrow$ `services/portal/`

> [!NOTE]
> **Entrypoint Standardization**:
> Main Flask web applications inside each service directory will be standardized to `app.py` (renaming `web_gui.py` $\rightarrow$ `app.py` inside `daq_usb4716`, `musashi_ii`, and `musashi_iv`).

---

## Open Questions

> [!QUESTION]
> 1. **Service Placement**: Do you prefer grouping all microservices under `services/` (`services/daq_usb4716`, `services/musashi_ii`, etc.), OR keeping services at the root level with standardized names (`daq_usb4716/`, `musashi_ii/`, `musashi_iv/`, `plotter/`, `portal/`)?
> 2. **Entrypoint Names**: Do you prefer standardizing all Flask entrypoints to `app.py` across services, or keeping `web_gui.py` names?

---

## Proposed Changes

### Directory Structure Comparison

#### Current Layout
```
DAQ-USB-4716/
├── USB4716/
├── musashi_II/
├── mushashi_IV/               # Typo in folder name
├── plot_service/
├── portal/
├── web_gui/                  # Empty directory
├── db_setup.sql/             # Empty directory!
├── pgdata/                   # Postgres cluster (gitignored)
├── deploy/
└── docs/
```

#### Proposed Refactored Layout
```
DAQ-USB-4716/
├── services/
│   ├── daq_usb4716/
│   │   ├── app.py            # (formerly web_gui.py)
│   │   ├── stream_to_db.py
│   │   ├── mockup_stream_to_db.py
│   │   ├── mqtt_to_db.py
│   │   ├── PolliingStream.py
│   │   ├── config.json
│   │   ├── static/
│   │   └── templates/
│   ├── musashi_ii/
│   │   ├── app.py            # (formerly web_gui.py)
│   │   ├── read_musashi.py
│   │   ├── database_handler.py
│   │   ├── config.json
│   │   ├── static/
│   │   └── templates/
│   ├── musashi_iv/           # Fixed typo
│   │   ├── app.py            # (formerly web_gui.py)
│   │   ├── stream_to_db.py
│   │   ├── api_client.py
│   │   ├── mock_api_server.py
│   │   ├── config.json
│   │   ├── static/
│   │   └── templates/
│   ├── plotter/
│   │   ├── app.py
│   │   ├── static/
│   │   └── templates/
│   └── portal/
│       ├── index.html
│       ├── app.js
│       └── style.css
├── shared/
│   ├── __init__.py
│   ├── config.py             # Centralized config & DSN resolver
│   ├── db.py                 # DB connection pool & table helpers
│   └── process_manager.py    # Daemon PID & state helpers
├── scripts/
│   └── sql/
│       └── db_setup.sql      # Replaces empty directory with actual SQL setup
├── deploy/
│   ├── linux/                # Updated Linux runners & systemd configs
│   └── windows/              # Updated Windows runners & Task Scheduler configs
├── docs/                     # Updated context documentation
└── README.md                 # Updated paths and architecture guide
```

---

### Key File Modifications & Additions

#### [NEW] `shared/__init__.py`, `shared/config.py`, `shared/db.py`, `shared/process_manager.py`
Modular utilities for configuration loading, process PID control, and database connections shared across microservices.

#### [NEW] `scripts/sql/db_setup.sql`
Full SQL schema definition script for initializing TimescaleDB / PostgreSQL tables (`daq_samples`, `daq_sessions`, `musashi_ii_data`, `musashi_iv_data`) and hypertables.

#### [DELETE] `db_setup.sql/` & `web_gui/` & `musashi_II/.venv/`
Remove empty/junk directories.

#### [MOVE & MODIFY] Services & Deployment Runners
- Update import statements and path references in `services/plotter/app.py`, `services/daq_usb4716/app.py`, `services/musashi_ii/app.py`, `services/musashi_iv/app.py`.
- Update `deploy/linux/run.sh`, `stop.sh`, `setup_systemd.sh`, `mddp.service`.
- Update `deploy/windows/run.bat`, `stop.bat`, `setup_task_scheduler.ps1`, `watchdog.ps1`.
- Update `README.md`, `DEPLOY_LINUX.md`, and `DEPLOY_WINDOWS.md`.

---

## Verification Plan

### Automated Tests
1. **Python Compilation & Syntax Check**:
   ```bash
   python3 -m py_compile shared/*.py services/*/*.py
   ```
2. **Import Integrity Check**:
   Verify all Flask web applications and ingestion scripts import successfully:
   ```bash
   python3 -c "import shared.config; import shared.db; import shared.process_manager; print('Shared modules loaded cleanly')"
   ```
3. **Deployment Runner Validation**:
   Run dry-run checks on `deploy/linux/run.sh` and `deploy/linux/stop.sh`.

### Manual Verification
1. Verify Portal Gateway loads at `http://localhost:8080`.
2. Verify DAQ USB-4716 Panel opens on `:8081`.
3. Verify Musashi II Panel opens on `:8082`.
4. Verify Musashi IV Panel opens on `:8083`.
5. Verify Database Plotter loads on `:8084`.
