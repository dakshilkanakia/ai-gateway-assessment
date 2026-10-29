from __future__ import annotations

import asyncio

import httpx
import pytest

from assessment.task4_model_router.app import create_app
from assessment.task4_model_router.rate_limiter import SqliteTokenRateLimiter


@pytest.mark.asyncio
async def test_exact_window_eviction(tmp_path) -> None:
    now = [1_000.0]
    limiter = SqliteTokenRateLimiter(tmp_path / "limit.db", limit=100, clock=lambda: now[0])
    assert (await limiter.consume("tenant", 60)).allowed
    denied = await limiter.consume("tenant", 41)
    assert not denied.allowed
    assert denied.used_tokens == 60
    now[0] += 60.001
    allowed = await limiter.consume("tenant", 100)
    assert allowed.allowed
    assert allowed.remaining_tokens == 0


@pytest.mark.asyncio
async def test_concurrent_admission_is_atomic(tmp_path) -> None:
    limiter = SqliteTokenRateLimiter(tmp_path / "concurrent.db", limit=100)
    decisions = await asyncio.gather(*(limiter.consume("same-tenant", 30) for _ in range(10)))
    assert sum(item.allowed for item in decisions) == 3


async def call_router(app, payload=None) -> httpx.Response:
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://router"
        ) as client:
            return await client.post(
                "/v1/completions",
                json=payload or {"prompt": "hello", "max_tokens": 5, "input_tokens": 5},
                headers={"X-API-Key": "tenant-a"},
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("primary_behavior", ["429", "timeout"])
async def test_fallback_on_429_or_timeout(tmp_path, primary_behavior) -> None:
    calls: list[str] = []

    async def provider(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host or "")
        if request.url.host == "primary":
            if primary_behavior == "timeout":
                raise httpx.ReadTimeout("secret upstream details", request=request)
            return httpx.Response(429, json={"internal": "do not leak"})
        return httpx.Response(200, json={"model": "backup", "text": "ok"})

    app = create_app(
        primary_url="http://primary/completions",
        secondary_url="http://secondary/completions",
        limiter=SqliteTokenRateLimiter(tmp_path / f"{primary_behavior}.db"),
        client=httpx.AsyncClient(transport=httpx.MockTransport(provider)),
    )
    response = await call_router(app)
    assert response.status_code == 200
    assert response.json()["model"] == "backup"
    assert calls == ["primary", "secondary"]


@pytest.mark.asyncio
async def test_wall_clock_deadline_triggers_fallback(tmp_path) -> None:
    async def provider(request: httpx.Request) -> httpx.Response:
        if request.url.host == "primary":
            await asyncio.sleep(0.05)
        return httpx.Response(200, json={"model": request.url.host})

    app = create_app(
        primary_url="http://primary/completions",
        secondary_url="http://secondary/completions",
        limiter=SqliteTokenRateLimiter(tmp_path / "deadline.db"),
        client=httpx.AsyncClient(transport=httpx.MockTransport(provider)),
        timeout_seconds=0.01,
    )
    response = await call_router(app)
    assert response.status_code == 200
    assert response.json()["model"] == "secondary"


@pytest.mark.asyncio
async def test_non_fallback_error_is_sanitized(tmp_path) -> None:
    async def provider(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"stack": "password=secret"})

    app = create_app(
        primary_url="http://primary/completions",
        secondary_url="http://secondary/completions",
        limiter=SqliteTokenRateLimiter(tmp_path / "error.db"),
        client=httpx.AsyncClient(transport=httpx.MockTransport(provider)),
    )
    response = await call_router(app)
    assert response.status_code == 502
    assert response.json() == {
        "error": {"code": "upstream_error", "message": "Model provider request failed"}
    }
    assert "secret" not in response.text


@pytest.mark.asyncio
async def test_router_enforces_token_limit_before_provider_call(tmp_path) -> None:
    calls = 0

    async def provider(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"text": "ok"})

    app = create_app(
        primary_url="http://primary/completions",
        secondary_url="http://secondary/completions",
        limiter=SqliteTokenRateLimiter(tmp_path / "small.db", limit=10),
        client=httpx.AsyncClient(transport=httpx.MockTransport(provider)),
    )
    first = await call_router(app)
    second = await call_router(app)
    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "rate_limit_exceeded"
    assert calls == 1

