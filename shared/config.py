import os
import json

def load_config(config_path):
    """
    Safely loads a JSON configuration file.
    """
    if not os.path.exists(config_path):
        return {}
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"[CONFIG] Failed to load config from {config_path}: {e}")
        return {}

def get_active_mode(mode_file_path):
    """
    Reads the active daemon process mode ('real' vs 'mockup').
    """
    if os.path.exists(mode_file_path):
        try:
            with open(mode_file_path, 'r', encoding='utf-8') as f:
                return f.read().strip()
        except Exception:
            pass
    return 'real'

def resolve_db_dsn(config_dict, mode_file_path=None):
    """
    Resolves the database DSN based on active execution mode.
    """
    active_mode = get_active_mode(mode_file_path) if mode_file_path else 'real'
    
    if active_mode == 'mockup':
        base_dsn = config_dict.get("MOCKUP_DB_DSN", "postgresql://admin:admin@localhost:5432/daq_db")
        if "/daq_db" in base_dsn:
            return base_dsn.replace("/daq_db", "/mockup")
        elif base_dsn.endswith("/"):
            return base_dsn + "mockup"
        else:
            slash_idx = base_dsn.rfind('/')
            if slash_idx != -1:
                return base_dsn[:slash_idx+1] + "mockup"
        return base_dsn
    else:
        return config_dict.get("DB_DSN", "postgresql://admin:admin@172.21.108.86:5432/daq_db")
