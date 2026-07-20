import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import auth, websocket


def test_login_failures_are_rate_limited_and_success_resets(monkeypatch):
    request = SimpleNamespace(client=SimpleNamespace(host="198.51.100.25"))
    monkeypatch.setattr(auth.settings, "LOGIN_RATE_LIMIT_ATTEMPTS", 2)
    monkeypatch.setattr(auth.settings, "LOGIN_RATE_LIMIT_WINDOW_SECONDS", 60)
    auth._login_failures.clear()

    asyncio.run(auth._record_login_result(request, False))
    asyncio.run(auth._record_login_result(request, False))
    with pytest.raises(HTTPException) as blocked:
        asyncio.run(auth._enforce_login_rate_limit(request))
    assert blocked.value.status_code == 429

    asyncio.run(auth._record_login_result(request, True))
    asyncio.run(auth._enforce_login_rate_limit(request))


def test_websocket_auth_token_uses_subprotocol_not_query_string():
    socket = SimpleNamespace(headers={
        "sec-websocket-protocol": "certiproof, auth.header-token",
    })

    assert websocket._websocket_token(socket) == "header-token"
