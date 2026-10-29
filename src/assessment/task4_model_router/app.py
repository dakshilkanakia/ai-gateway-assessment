"""Rate-limited LLM router with timeout/429 fallback."""

from __future__ import annotations

import asyncio
import logging
import math
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .rate_limiter import SqliteTokenRateLimiter

logger = logging.getLogger(__name__)


class CompletionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    prompt: str = Field(min_length=1)
    max_tokens: int = Field(default=256, gt=0, le=32_000)
    input_tokens: int | None = Field(default=None, gt=0)

    def reserved_tokens(self) -> int:
        # The caller may provide tokenizer output. Four chars/token is a safe,
        # transparent fallback for this provider-agnostic assessment router.
        input_count = self.input_tokens or max(1, math.ceil(len(self.prompt) / 4))
        return input_count + self.max_tokens


def gateway_error(code: str, message: str, status_code: int, **extra: Any) -> JSONResponse:
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    body["error"].update(extra)
    return JSONResponse(body, status_code=status_code)


def create_app(
    *,
    primary_url: str,
    secondary_url: str,
    limiter: SqliteTokenRateLimiter,
    client: httpx.AsyncClient | None = None,
    timeout_seconds: float = 3.0,
) -> FastAPI:
    owned_client = client is None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.client = client or httpx.AsyncClient()
        yield
        if owned_client:
            await app.state.client.aclose()

    app = FastAPI(title="Rate-Limited Model Router", lifespan=lifespan)

    async def call_provider(url: str, body: dict[str, Any]) -> httpx.Response:
        # This is an absolute wall-clock deadline. A socket read timeout alone
        # can be kept alive indefinitely by periodic tiny chunks.
        async with asyncio.timeout(timeout_seconds):
            return await app.state.client.post(url, json=body, timeout=timeout_seconds)

    @app.post("/v1/completions")
    async def complete(
        payload: CompletionRequest,
        request: Request,
        api_key: str | None = Header(default=None, alias="X-API-Key"),
    ) -> JSONResponse:
        if not api_key:
            return gateway_error("authentication_required", "Missing API key", 401)

        try:
            decision = await limiter.consume(api_key, payload.reserved_tokens())
        except (sqlite3.Error, OSError):
            logger.exception("rate limiter storage failed")
            return gateway_error("gateway_unavailable", "Gateway temporarily unavailable", 503)
        if not decision.allowed:
            return gateway_error(
                "rate_limit_exceeded",
                "Tenant token limit exceeded",
                429,
                retry_after_seconds=round(decision.retry_after_seconds, 3),
            )

        body = payload.model_dump(exclude={"input_tokens"})
        use_fallback = False
        try:
            upstream = await call_provider(primary_url, body)
            use_fallback = upstream.status_code == 429
            if not use_fallback and upstream.is_error:
                logger.error("primary provider returned status=%s", upstream.status_code)
                return gateway_error("upstream_error", "Model provider request failed", 502)
        except (TimeoutError, httpx.TimeoutException):
            logger.warning("primary provider timed out; using fallback")
            use_fallback = True
        except httpx.HTTPError:
            logger.exception("primary provider transport failure")
            return gateway_error("upstream_error", "Model provider unavailable", 502)

        if use_fallback:
            try:
                upstream = await call_provider(secondary_url, body)
                if upstream.is_error:
                    logger.error("fallback provider returned status=%s", upstream.status_code)
                    return gateway_error("upstream_error", "All model providers failed", 502)
            except (TimeoutError, httpx.HTTPError):
                logger.exception("fallback provider failed")
                return gateway_error("upstream_error", "All model providers failed", 502)

        try:
            result = upstream.json()
        except ValueError:
            return gateway_error("invalid_upstream_response", "Model provider returned invalid data", 502)
        return JSONResponse(result)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, __: RequestValidationError) -> JSONResponse:
        return gateway_error("invalid_request", "Invalid completion request", 422)

    return app

