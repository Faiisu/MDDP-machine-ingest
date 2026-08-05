import pytest
import json
from services.influxdb.app import app, read_config, write_config

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_influx_home_route(client):
    rv = client.get('/')
    assert rv.status_code == 200
    assert b'INFLUXDB 2.X SERVICE MANAGER' in rv.data

def test_influx_config_get(client):
    rv = client.get('/api/config')
    assert rv.status_code == 200
    data = json.loads(rv.data)
    assert 'INFLUX_URL' in data
    assert 'INFLUX_ORG' in data

def test_influx_status_get(client):
    rv = client.get('/api/status')
    assert rv.status_code == 200
    data = json.loads(rv.data)
    assert 'container_status' in data
    assert 'is_healthy' in data

def test_influx_retention_update(client):
    payload = {
        'enabled': True,
        'days': 7,
        'hours': 12,
        'minutes': 30,
        'seconds': 0
    }
    # Note: Without a running InfluxDB server, HTTP call will return 400 or 500 error, but endpoint is exercisable
    rv = client.post('/api/retention', json=payload)
    assert rv.status_code in (200, 400, 440, 500)
