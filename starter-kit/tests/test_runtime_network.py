"""Runtime connection failures must return to the runner without long waits."""

import httpx
import pytest

from csee.__main__ import runtime_client


def test_retry_keeps_move_id_and_long_supplier_read_budget(monkeypatch):
    monkeypatch.setattr("arena_kit.client.time.sleep", lambda seconds: None)
    attempts = []

    def handle(request):
        attempts.append(request)
        assert request.extensions["timeout"] == {"connect": 5, "read": 180, "write": 15, "pool": 5}
        if len(attempts) < 3:
            raise httpx.ConnectTimeout("temporary connection loss", request=request)
        return httpx.Response(200, json={"recovered": True})

    client = runtime_client(base_url="https://arena.test", api_key="test", transport=httpx.MockTransport(handle))
    try:
        assert client.send_message("session", "supplier", {"body": "Our offer"}) == {"recovered": True}
    finally:
        client.http.close()
    assert len(attempts) == 3
    assert len({r.headers["X-Move-Id"] for r in attempts}) == 1
    assert len({r.content for r in attempts}) == 1


def test_persistent_connect_failure_returns_after_two_retries(monkeypatch):
    monkeypatch.setattr("arena_kit.client.time.sleep", lambda seconds: None)
    attempts = []

    def handle(request):
        attempts.append(request)
        raise httpx.ConnectTimeout("offline", request=request)

    client = runtime_client(base_url="https://arena.test", api_key="test", transport=httpx.MockTransport(handle))
    try:
        with pytest.raises(httpx.ConnectTimeout):
            client.me()
    finally:
        client.http.close()
    assert len(attempts) == 3
