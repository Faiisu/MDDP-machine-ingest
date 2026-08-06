import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, jsonify, render_template


SERVICE_CATALOG = (
    {"id": "daq", "name": "DAQ USB-4716", "port": 8081, "path": "/"},
    {"id": "musashi-ii", "name": "Musashi II", "port": 8082, "path": "/"},
    {"id": "musashi-iv", "name": "Musashi IV", "port": 8083, "path": "/"},
    {"id": "plotter", "name": "Database Plotter", "port": 8084, "path": "/"},
    {"id": "influx-manager", "name": "InfluxDB Manager", "port": 18085, "path": "/"},
    {"id": "influx", "name": "InfluxDB Server", "port": 8086, "path": "/health"},
)

app = Flask(__name__, template_folder="templates", static_folder="static")


def probe_service(service):
    url = f"http://127.0.0.1:{service['port']}{service['path']}"
    request = urllib.request.Request(url, headers={"User-Agent": "MDDP-Service-Portal"})
    try:
        with urllib.request.urlopen(request, timeout=1.5) as response:
            return {
                **service,
                "status": "online" if response.status < 400 else "degraded",
                "http_status": response.status,
                "url": url,
            }
    except (OSError, urllib.error.URLError, urllib.error.HTTPError) as error:
        return {**service, "status": "offline", "http_status": None, "url": url, "error": str(error)}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/services")
def service_status():
    with ThreadPoolExecutor(max_workers=len(SERVICE_CATALOG)) as executor:
        services = list(executor.map(probe_service, SERVICE_CATALOG))
    online_count = sum(service["status"] == "online" for service in services)
    return jsonify({"services": services, "online": online_count, "total": len(services)})


if __name__ == "__main__":
    print("[SYSTEM] Starting MDDP Service Portal on Port 8080...")
    app.run(host="0.0.0.0", port=8080, debug=False)
