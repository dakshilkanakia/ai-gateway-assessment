"""Runnable downstream server used for demos and manual verification."""

from __future__ import annotations

import os
from typing import Any

import uvicorn
from fastapi import FastAPI

app = FastAPI(title="Mock MCP Downstream")


@app.post("/mcp")
async def mcp_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
    request_id = payload.get("id")
    if payload.get("method") == "tools/list":
        result: Any = {
            "tools": [
                {"name": "get_status", "inputSchema": {"type": "object"}},
                {"name": "admin_reset_key", "inputSchema": {"type": "object"}},
            ]
        }
    else:
        result = {"forwarded": True, "tool": payload.get("params", {}).get("name")}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def run() -> None:
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("PORT", "9001")))


if __name__ == "__main__":
    run()
