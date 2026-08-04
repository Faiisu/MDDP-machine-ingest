#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
api_client.py
─────────────
Musashi IV Robot Dispenser API Client.
Fetches channel data from HTTP GET http://<IP>:<PORT>/v1/info/channel/data/<ch>
and formats response for database ingestion.
"""

import json
import logging
import urllib.request
import urllib.error
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

DEFAULT_API_URL = "http://172.16.48.198:1025/v1/info/channel/data/1"

def fetch_channel_data(api_url=DEFAULT_API_URL, timeout=5.0):
    """
    Fetches raw channel data from Musashi IV REST API.
    
    Format: curl -X GET http://172.16.48.198:1025/v1/info/channel/data/1
    Expected response:
    {
      "ch": [
        {
          "no": 0, "shotMode": 0, "disPress": 40.0, "disVacuum": 0.00, "disTime": 1.000,
          "chName": "", "syringeSize": 0, "tubeLength": 1.0, "usePlunger": 0, "airEco": 0,
          "onDelay": 0.000, "offDelay": 0.000, "watchPermit": 100.0, "watchMinOffTime": 0.500,
          "watchResult": 0, "sigmaMode": 0, "dummyShot": 0, "volRedCorr": 1, "corrAlpha": 0,
          "corrDelta": 100, "dropPrevent": 1, "corrVac": 0.00, "rsmDetect": 1, "rsmLevel": 10,
          "rsmCount": 5, "rsmCorrOnOff": 0, "rsmCorr": 0,
          "rsmMeasure": [0,0,0,0,0,0,0,0,0,0], "rsmUserSet": [0,0,0,0,0,0,0,0,0,0],
          "d0": 100, "d1": [255,255,255,255,255,255,255,255],
          "d2": [255,255,255,255,255,255,255,255], "d3": [255,255,255,255],
          "bkupCorrTime": 0.000, "bkupCorrPress": 0.0, "bkupCorrVac": 0.00
        }
      ]
    }
    """
    req = urllib.request.Request(
        url=api_url,
        headers={"User-Agent": "MusashiIV-IngestionClient/1.0", "Accept": "application/json"},
        method="GET"
    )
    
    fetch_ts = datetime.now(timezone.utc)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status == 200:
                body = response.read().decode("utf-8")
                data = json.loads(body)
                return {
                    "success": True,
                    "timestamp": fetch_ts,
                    "data": data,
                    "raw_body": body,
                    "error": None
                }
            else:
                return {
                    "success": False,
                    "timestamp": fetch_ts,
                    "data": None,
                    "raw_body": None,
                    "error": f"HTTP status {response.status}"
                }
    except urllib.error.URLError as e:
        return {
            "success": False,
            "timestamp": fetch_ts,
            "data": None,
            "raw_body": None,
            "error": f"URL Error: {e.reason}"
        }
    except Exception as e:
        return {
            "success": False,
            "timestamp": fetch_ts,
            "data": None,
            "raw_body": None,
            "error": f"Exception: {str(e)}"
        }

def format_channel_data(raw_payload, timestamp=None):
    """
    Parses and formats raw API response payload into database table fields.
    """
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
        
    data = raw_payload.get("data") if isinstance(raw_payload, dict) and "data" in raw_payload else raw_payload
    
    if not isinstance(data, dict) or "ch" not in data or not isinstance(data["ch"], list) or len(data["ch"]) == 0:
        raise ValueError("Invalid Musashi IV API response structure: missing 'ch' array")

    ch_obj = data["ch"][0]
    
    formatted_record = {
        "time": timestamp,
        "ch_no": int(ch_obj.get("no", 0)),
        "shot_mode": int(ch_obj.get("shotMode", 0)),
        "dis_press": float(ch_obj.get("disPress", 0.0)),
        "dis_vacuum": float(ch_obj.get("disVacuum", 0.0)),
        "dis_time": float(ch_obj.get("disTime", 0.0)),
        "ch_name": str(ch_obj.get("chName", "")),
        "syringe_size": int(ch_obj.get("syringeSize", 0)),
        "tube_length": float(ch_obj.get("tubeLength", 0.0)),
        "use_plunger": int(ch_obj.get("usePlunger", 0)),
        "air_eco": int(ch_obj.get("airEco", 0)),
        "on_delay": float(ch_obj.get("onDelay", 0.0)),
        "off_delay": float(ch_obj.get("offDelay", 0.0)),
        "watch_permit": float(ch_obj.get("watchPermit", 0.0)),
        "watch_min_off_time": float(ch_obj.get("watchMinOffTime", 0.0)),
        "watch_result": int(ch_obj.get("watchResult", 0)),
        "sigma_mode": int(ch_obj.get("sigmaMode", 0)),
        "dummy_shot": int(ch_obj.get("dummyShot", 0)),
        "vol_red_corr": int(ch_obj.get("volRedCorr", 0)),
        "corr_alpha": int(ch_obj.get("corrAlpha", 0)),
        "corr_delta": int(ch_obj.get("corrDelta", 0)),
        "drop_prevent": int(ch_obj.get("dropPrevent", 0)),
        "corr_vac": float(ch_obj.get("corrVac", 0.0)),
        "rsm_detect": int(ch_obj.get("rsmDetect", 0)),
        "rsm_level": int(ch_obj.get("rsmLevel", 0)),
        "rsm_count": int(ch_obj.get("rsmCount", 0)),
        "rsm_corr_on_off": int(ch_obj.get("rsmCorrOnOff", 0)),
        "rsm_corr": int(ch_obj.get("rsmCorr", 0)),
        "rsm_measure": json.dumps(ch_obj.get("rsmMeasure", [])),
        "rsm_user_set": json.dumps(ch_obj.get("rsmUserSet", [])),
        "d0": int(ch_obj.get("d0", 0)),
        "d1": json.dumps(ch_obj.get("d1", [])),
        "d2": json.dumps(ch_obj.get("d2", [])),
        "d3": json.dumps(ch_obj.get("d3", [])),
        "bkup_corr_time": float(ch_obj.get("bkupCorrTime", 0.0)),
        "bkup_corr_press": float(ch_obj.get("bkupCorrPress", 0.0)),
        "bkup_corr_vac": float(ch_obj.get("bkupCorrVac", 0.0)),
        "raw_json": json.dumps(data)
    }
    
    return formatted_record

if __name__ == "__main__":
    print("[TEST] Testing fetch_channel_data...")
    res = fetch_channel_data()
    print("Fetch result:", res)
    if res["success"]:
        formatted = format_channel_data(res["data"])
        print("Formatted record:", formatted)
