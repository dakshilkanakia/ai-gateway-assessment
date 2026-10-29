from __future__ import annotations

import os

import uvicorn

from .app import create_app

app = create_app(provider_url=os.getenv("LLM_PROVIDER_URL", "http://127.0.0.1:9101/generate"))


def run() -> None:
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("PORT", "9100")))


if __name__ == "__main__":
    run()
