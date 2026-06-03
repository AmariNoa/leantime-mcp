# SPDX-FileCopyrightText: 2026 AmariNoa
#
# SPDX-License-Identifier: MIT

"""Regression tests for dual authentication (API key vs PAT) and comment
attribution (Co-Authored-By trailer).

Guards against:
- regressing the auth header selection (X-API-KEY vs Authorization: Bearer),
- accidentally sending the API key alongside a PAT (which would let the server's
  api guard win and act as the bot instead of the human),
- the Co-Authored-By trailer being dropped, duplicated, or applied when unset.
"""

import asyncio

import pytest

from leantime_mcp.client import LeantimeClient
import leantime_mcp.server as server


class _FakeResponse:
    def __init__(self):
        self._captured = None

    def raise_for_status(self):
        return None

    def json(self):
        return {"jsonrpc": "2.0", "result": "ok", "id": 1}


async def _capture_headers(client_obj, monkeypatch):
    """Run a call() and return the headers that would be sent."""
    captured = {}

    class _FakeAsyncClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None, headers=None, timeout=None):
            captured["headers"] = headers
            return _FakeResponse()

    import leantime_mcp.client as client_mod
    monkeypatch.setattr(client_mod.httpx, "AsyncClient", _FakeAsyncClient)
    await client_obj.call("leantime.rpc.Auth.getUserId", {})
    return captured["headers"]


def test_requires_api_key_or_pat():
    with pytest.raises(ValueError):
        LeantimeClient("https://example.com")


def test_api_key_header_when_no_pat(monkeypatch):
    c = LeantimeClient("https://example.com", api_key="KEY", pat=None)
    headers = asyncio.run(_capture_headers(c, monkeypatch))
    assert headers["X-API-KEY"] == "KEY"
    assert "Authorization" not in headers


def test_pat_sends_bearer_only(monkeypatch):
    # PAT must win and the API key must NOT be sent, or the server's api guard
    # would authenticate as the bot instead of the token's human owner.
    c = LeantimeClient("https://example.com", api_key="KEY", pat="TOKEN")
    headers = asyncio.run(_capture_headers(c, monkeypatch))
    assert headers["Authorization"] == "Bearer TOKEN"
    assert "X-API-KEY" not in headers


def test_attribution_unset_is_noop(monkeypatch):
    monkeypatch.delenv("LEANTIME_AGENT_NAME", raising=False)
    assert server._with_attribution("hello") == "hello"


def test_attribution_appends_trailer(monkeypatch):
    monkeypatch.setenv("LEANTIME_AGENT_NAME", "Claude Code")
    assert server._with_attribution("hello") == "hello\n\nCo-Authored-By: Claude Code"


def test_attribution_is_idempotent(monkeypatch):
    monkeypatch.setenv("LEANTIME_AGENT_NAME", "Claude Code")
    once = server._with_attribution("hello")
    assert server._with_attribution(once) == once


def test_attribution_blank_name_is_noop(monkeypatch):
    monkeypatch.setenv("LEANTIME_AGENT_NAME", "   ")
    assert server._with_attribution("hello") == "hello"
