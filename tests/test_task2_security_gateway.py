from __future__ import annotations

import json

import httpx
import pytest

from assessment.task2_security_gateway.app import create_app


@pytest.fixture
def downstream() -> tuple[httpx.AsyncClient, list[dict]]:
    calls: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        body = calls[-1]
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body.get("id"), "result": {"ok": True}})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), calls


async def request_app(app, payload, token="viewer-token") -> httpx.Response:
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway"
        ) as client:
            return await client.post(
                "/mcp", json=payload, headers={"Authorization": f"Bearer {token}"}
            )


@pytest.mark.asyncio
async def test_tools_list_is_forwarded_unchanged(downstream) -> None:
    client, calls = downstream
    app = create_app(
        downstream_url="http://downstream/mcp",
        tokens={"viewer-token": "viewer"},
        client=client,
    )
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    response = await request_app(app, payload)
    assert response.status_code == 200
    assert calls == [payload]


@pytest.mark.asyncio
async def test_viewer_admin_call_is_intercepted_without_downstream_io(downstream) -> None:
    client, calls = downstream
    app = create_app(
        downstream_url="http://downstream/mcp",
        tokens={"viewer-token": "viewer"},
        client=client,
    )
    response = await request_app(
        app,
        {"jsonrpc": "2.0", "id": "abc", "method": "tools/call", "params": {"name": "admin_reset_key"}},
    )
    assert response.status_code == 403
    assert response.json() == {
        "jsonrpc": "2.0",
        "id": "abc",
        "error": {"code": -32001, "message": "Unauthorized Tool Call"},
    }
    assert calls == []


@pytest.mark.asyncio
async def test_admin_and_normal_calls_are_forwarded(downstream) -> None:
    client, calls = downstream
    app = create_app(
        downstream_url="http://downstream/mcp",
        tokens={"admin-token": "admin", "viewer-token": "viewer"},
        client=client,
    )
    for token, name in (("admin-token", "admin_reset_key"), ("viewer-token", "get_status")):
        response = await request_app(
            app,
            {"jsonrpc": "2.0", "id": name, "method": "tools/call", "params": {"name": name}},
            token,
        )
        assert response.status_code == 200
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_auth_and_jsonrpc_errors(downstream) -> None:
    client, calls = downstream
    app = create_app(
        downstream_url="http://downstream/mcp", tokens={"viewer-token": "viewer"}, client=client
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway"
        ) as gateway:
            assert (await gateway.post("/mcp", json={})).status_code == 401
            malformed = await gateway.post(
                "/mcp", content="{", headers={"Authorization": "Bearer viewer-token"}
            )
            assert malformed.json()["error"]["code"] == -32700
            invalid = await gateway.post(
                "/mcp", json={"jsonrpc": "1.0", "id": 9, "method": "x"},
                headers={"Authorization": "Bearer viewer-token"},
            )
            assert invalid.json()["error"]["code"] == -32600
    assert calls == []

