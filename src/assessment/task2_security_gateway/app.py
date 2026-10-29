"""MCP security gateway application factory."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from assessment.common.jsonrpc import JsonRpcRequest, error_response

from .auth import TokenAuthenticator

logger = logging.getLogger(__name__)


def create_app(
    *,
    downstream_url: str,
    tokens: dict[str, str],
    client: httpx.AsyncClient | None = None,
) -> FastAPI:
    owned_client = client is None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if owned_client:
            app.state.client = httpx.AsyncClient(timeout=10.0)
        else:
            app.state.client = client
        yield
        if owned_client:
            await app.state.client.aclose()

    app = FastAPI(title="MCP Security Gateway", lifespan=lifespan)
    authenticator = TokenAuthenticator(tokens)

    @app.post("/mcp")
    async def proxy(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> Response:
        principal = authenticator.authenticate(authorization)
        try:
            raw: Any = await request.json()
        except json.JSONDecodeError:
            return JSONResponse(error_response(None, -32700, "Parse error"), status_code=400)

        request_id = raw.get("id") if isinstance(raw, dict) else None
        try:
            rpc = JsonRpcRequest.model_validate(raw)
        except ValidationError:
            return JSONResponse(
                error_response(request_id, -32600, "Invalid Request"),
                status_code=400,
            )

        if rpc.method == "tools/call":
            tool_name = (rpc.params or {}).get("name")
            if not isinstance(tool_name, str):
                return JSONResponse(
                    error_response(rpc.id, -32602, "Invalid params"),
                    status_code=400,
                )
            if tool_name.startswith("admin_") and principal.role != "admin":
                logger.warning("denied tool=%s role=%s", tool_name, principal.role)
                return JSONResponse(
                    error_response(rpc.id, -32001, "Unauthorized Tool Call"),
                    status_code=403,
                )

        # tools/list and all other valid MCP methods are forwarded unchanged.
        try:
            upstream = await request.app.state.client.post(
                downstream_url,
                content=await request.body(),
                headers={"content-type": request.headers.get("content-type", "application/json")},
            )
        except httpx.RequestError:
            logger.exception("downstream MCP request failed")
            return JSONResponse(
                error_response(rpc.id, -32000, "Downstream MCP server unavailable"),
                status_code=502,
            )
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type", "application/json"),
        )

    return app

