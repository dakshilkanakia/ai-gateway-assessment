from __future__ import annotations

import os

import uvicorn

from .app import create_app


def _tokens_from_env() -> dict[str, str]:
    # Format: MCP_TOKENS="admin-secret:admin,viewer-secret:viewer"
    raw = os.getenv("MCP_TOKENS", "admin-secret:admin,viewer-secret:viewer")
    return dict(item.split(":", 1) for item in raw.split(",") if ":" in item)


app = create_app(
    downstream_url=os.getenv("MCP_DOWNSTREAM_URL", "http://127.0.0.1:9001/mcp"),
    tokens=_tokens_from_env(),
)


def run() -> None:
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("PORT", "9000")))


if __name__ == "__main__":
    run()

