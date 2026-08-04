#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mock_api_server.py
──────────────────
Mock server simulating Musashi IV REST API response.
Serves GET /v1/info/channel/data/<ch_no> on port 1025.
"""

import sys
import json
import math
import time
import random
from http.server import HTTPServer, BaseHTTPRequestHandler

class MusashiIVMockHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/v1/info/channel/data"):
            # Extract channel number if provided
            parts = self.path.rstrip('/').split('/')
            ch_no = int(parts[-1]) if parts[-1].isdigit() else 0
            
            # Generate realistic fluctuating values for pressure, vacuum, time
            t = time.time()
            dis_press = round(40.0 + 2.5 * math.sin(t / 5.0) + random.uniform(-0.2, 0.2), 2)
            dis_vac = round(max(0.0, 0.05 * math.cos(t / 10.0)), 2)
            dis_time = round(1.000 + 0.01 * math.sin(t / 3.0), 3)

            sample_response = {
                "ch": [
                    {
                        "no": ch_no,
                        "shotMode": 0,
                        "disPress": dis_press,
                        "disVacuum": dis_vac,
                        "disTime": dis_time,
                        "chName": f"CH_{ch_no}_DISPENSER",
                        "syringeSize": 0,
                        "tubeLength": 1.0,
                        "usePlunger": 0,
                        "airEco": 0,
                        "onDelay": 0.000,
                        "offDelay": 0.000,
                        "watchPermit": 100.0,
                        "watchMinOffTime": 0.500,
                        "watchResult": 0,
                        "sigmaMode": 0,
                        "dummyShot": 0,
                        "volRedCorr": 1,
                        "corrAlpha": 0,
                        "corrDelta": 100,
                        "dropPrevent": 1,
                        "corrVac": 0.00,
                        "rsmDetect": 1,
                        "rsmLevel": 10,
                        "rsmCount": 5,
                        "rsmCorrOnOff": 0,
                        "rsmCorr": 0,
                        "rsmMeasure": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                        "rsmUserSet": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                        "d0": 100,
                        "d1": [255, 255, 255, 255, 255, 255, 255, 255],
                        "d2": [255, 255, 255, 255, 255, 255, 255, 255],
                        "d3": [255, 255, 255, 255],
                        "bkupCorrTime": 0.000,
                        "bkupCorrPress": 0.0,
                        "bkupCorrVac": 0.00
                    }
                ]
            }

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(sample_response).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error": "Not Found"}')

    def log_message(self, format, *args):
        # Suppress routine log output to keep console clean
        pass

def run_mock_server(port=1025):
    server_address = ('', port)
    httpd = HTTPServer(server_address, MusashiIVMockHandler)
    print(f"[MOCK_API] Musashi IV Mock API server running on port {port}...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("[MOCK_API] Stopping mock server.")
        httpd.server_close()

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 1025
    run_mock_server(port)
