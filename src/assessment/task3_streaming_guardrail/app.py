"""SSE-to-SSE LLM proxy with streaming delta redaction."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict

from .redactor import StreamingRedactor

logger = logging.getLogger(__name__)


class GenerationRequest(BaseModel):
    model_config = ConfigDict(extra="allow")
    prompt: str


def _sse(delta: str) -> bytes:
    return f"data: {json.dumps({'delta': delta}, separators=(',', ':'))}\n\n".encode()


def create_app(
    *,
    provider_url: str,
    client: httpx.AsyncClient | None = None,
) -> FastAPI:
    owned_client = client is None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.client = client or httpx.AsyncClient(timeout=None)
        yield
        if owned_client:
            await app.state.client.aclose()

    app = FastAPI(title="Streaming PII Guardrail", lifespan=lifespan)

    @app.post("/v1/generate")
    async def generate(payload: GenerationRequest, request: Request) -> StreamingResponse:
        async def guarded_stream() -> AsyncIterator[bytes]:
            redactor = StreamingRedactor()
            try:
                async with request.app.state.client.stream(
                    "POST", provider_url, json=payload.model_dump()
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        value = line[5:].strip()
                        if value == "[DONE]":
                            break
                        try:
                            event: dict[str, Any] = json.loads(value)
                            delta = event.get("delta", "")
                        except (json.JSONDecodeError, AttributeError):
                            logger.warning("ignored malformed provider stream event")
                            continue
                        if not isinstance(delta, str):
                            continue
                        if safe := redactor.feed(delta):
                            yield _sse(safe)
                if tail := redactor.flush():
                    yield _sse(tail)
                yield b"data: [DONE]\n\n"
            except httpx.HTTPError:
                logger.exception("provider stream failed")
                error = {"error": {"code": "upstream_error", "message": "Provider stream failed"}}
                yield f"data: {json.dumps(error, separators=(',', ':'))}\n\n".encode()

        return StreamingResponse(guarded_stream(), media_type="text/event-stream")

    @app.exception_handler(httpx.HTTPError)
    async def upstream_error(_: Request, __: httpx.HTTPError) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": "upstream_error", "message": "Provider unavailable"}},
            status_code=502,
        )

    return app

