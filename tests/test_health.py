import pytest

flask = pytest.importorskip('flask')

from app_advanced import app as flask_app


def test_health_endpoint():
    client = flask_app.test_client()
    response = client.get('/api/health')
    assert response.status_code == 200
    data = response.get_json()
    assert data is not None
    assert data.get('status') == 'ok'
    assert 'version' in data
