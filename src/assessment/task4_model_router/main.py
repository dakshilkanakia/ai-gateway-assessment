from __future__ import annotations

import os
from pathlib import Path

import uvicorn

from .app import create_app
from .rate_limiter import SqliteTokenRateLimiter

limiter = SqliteTokenRateLimiter(
    Path(os.getenv("RATE_LIMIT_DB", "rate_limits.db")),
    limit=int(os.getenv("TOKEN_LIMIT_PER_MINUTE", "50000")),
)
app = create_app(
    primary_url=os.getenv("PRIMARY_MODEL_URL", "http://127.0.0.1:9201/v1/completions"),
    secondary_url=os.getenv("SECONDARY_MODEL_URL", "http://127.0.0.1:9202/v1/completions"),
    limiter=limiter,
)


def run() -> None:
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("PORT", "9200")))


if __name__ == "__main__":
    run()
