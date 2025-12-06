import os
import json
import pytest
import requests
from app_advanced import app


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def test_ai_chat_proxy_missing_key(client, monkeypatch):
    # Ensure env var not set
    monkeypatch.delenv('GROQ_API_KEY', raising=False)
    payload = {"messages": [{"role": "user", "content": "Test message"}], "model": "gpt-4o-mini"}
    res = client.post('/api/ai/chat', json=payload)
    assert res.status_code == 400
    data = res.get_json()
    assert 'GROQ_API_KEY' in data['error'] or 'not configured' in data['error']


def test_ai_chat_proxy_forwarding(client, monkeypatch):
    # Mock server key set
    monkeypatch.setenv('GROQ_API_KEY', 'fake_key')

    class FakeResp:
        def __init__(self, body, status=200):
            self._body = body
            self.status_code = status
        def json(self):
            return self._body

    def fake_post(url, headers=None, json=None, timeout=None):
        # Ensure the URL is the GROQ chat completions endpoint
        assert 'api.groq.com' in url
        return FakeResp({
            'choices': [
                {'message': {'role': 'assistant', 'content': 'Mocked response'}}
            ]
        }, 200)

    monkeypatch.setattr(requests, 'post', fake_post)

    payload = {"messages": [{"role": "user", "content": "Test message"}], "model": "gpt-4o-mini"}
    res = client.post('/api/ai/chat', json=payload)
    assert res.status_code == 200
    data = res.get_json()
    assert data['choices'][0]['message']['content'] == 'Mocked response'


def test_ai_chat_proxy_invalid_payload(client, monkeypatch):
    monkeypatch.setenv('GROQ_API_KEY', 'fake_key')

    class FakeResp:
        def __init__(self, body, status=200):
            self._body = body
            self.status_code = status
        def json(self):
            return self._body

    def fake_post(url, headers=None, json=None, timeout=None):
        return FakeResp({})

    monkeypatch.setattr('requests.post', fake_post)

    # Missing required fields (no model/messages)
    res = client.post('/api/ai/chat', json={})
    assert res.status_code == 400
    data = res.get_json()
    assert 'Request must include' in data['error']
