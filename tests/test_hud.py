"""HUD API: métricas reales, sin red ni GUI."""
import importlib

import pytest

flask = pytest.importorskip('flask')

hud_app = importlib.import_module('hud.app')


@pytest.fixture()
def client():
    hud_app.app.config['TESTING'] = True
    with hud_app.app.test_client() as client:
        yield client


def test_index_serves_page(client):
    response = client.get('/')
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'JARVIS' in body and '/api/stats' in body and 'Orbitron' in body


def test_stats_payload_shape_and_ranges(client):
    response = client.get('/api/stats')
    assert response.status_code == 200
    data = response.get_json()
    for key in ('server_time', 'uptime_seconds', 'cpu_percent', 'per_core', 'cpu_count',
                'ram', 'swap', 'disk', 'net', 'battery', 'processes', 'health',
                'environment', 'modules', 'all_systems_operational'):
        assert key in data, key
    assert 0 <= data['cpu_percent'] <= 100
    assert len(data['per_core']) == data['cpu_count'] >= 1
    assert all(0 <= core <= 100 for core in data['per_core'])
    assert 0 <= data['ram']['percent'] <= 100 and data['ram']['total_gb'] > 0
    assert 0 <= data['swap']['percent'] <= 100
    assert data['uptime_seconds'] >= 0 and data['processes'] >= 1
    assert 0 <= data['health'] <= 100
    assert set(data['modules']) == {'VOICE', 'VISION', 'NETWORK', 'MEMORY', 'CORE'}
    assert all(v in (0, 100) for v in data['modules'].values())
