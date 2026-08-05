import services.portal.app as portal
import pytest


@pytest.fixture
def client():
    portal.app.config['TESTING'] = True
    with portal.app.test_client() as test_client:
        yield test_client


def test_portal_home(client):
    response = client.get('/')
    assert response.status_code == 200
    assert b'MDDP Service Portal' in response.data
    assert b'/static/style.css' in response.data
    assert b'/static/app.js' in response.data


def test_portal_assets(client):
    stylesheet = client.get('/static/style.css')
    script = client.get('/static/app.js')

    assert stylesheet.status_code == 200
    assert stylesheet.content_type.startswith('text/css')
    assert script.status_code == 200
    assert script.content_type.startswith('text/javascript')


def test_portal_service_status(monkeypatch, client):
    def fake_probe(service):
        return {**service, 'status': 'online', 'http_status': 200, 'url': 'http://127.0.0.1'}

    monkeypatch.setattr(portal, 'probe_service', fake_probe)
    response = client.get('/api/services')
    data = response.get_json()

    assert response.status_code == 200
    assert data['online'] == data['total'] == 6
    assert {service['port'] for service in data['services']} == {8081, 8082, 8083, 8084, 8085, 8086}
