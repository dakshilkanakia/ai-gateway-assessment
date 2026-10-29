from __future__ import annotations

import json

import httpx
import pytest

from assessment.task3_streaming_guardrail.app import create_app
from assessment.task3_streaming_guardrail.redactor import StreamingRedactor, redact_pii


def test_complete_redaction_patterns() -> None:
    value = "Email ada@example.com SSN 123-45-6789 card 4111 1111 1111 1111."
    redacted = redact_pii(value)
    assert "ada@example.com" not in redacted
    assert "123-45-6789" not in redacted
    assert "4111 1111 1111 1111" not in redacted
    assert redacted.count("[REDACTED]") == 3


def test_patterns_split_at_every_chunk_boundary() -> None:
    text = "Contact ada@example.com or use 123-45-6789 safely."
    for split in range(1, len(text)):
        redactor = StreamingRedactor()
        output = redactor.feed(text[:split]) + redactor.feed(text[split:]) + redactor.flush()
        assert output == "Contact [REDACTED] or use [REDACTED] safely."


def test_pending_memory_is_bounded_for_unbroken_input() -> None:
    redactor = StreamingRedactor(max_carry=256)
    emitted = redactor.feed("x" * 10_000)
    assert len(emitted) == 10_000 - 256
    assert redactor.pending_size == 256


@pytest.mark.asyncio
async def test_proxy_redacts_provider_sse_across_events() -> None:
    async def provider(_: httpx.Request) -> httpx.Response:
        events = ["Reach ada@", "example.com and ", "123-45-", "6789 now."]
        content = b"".join(
            f"data: {json.dumps({'delta': event})}\n\n".encode() for event in events
        ) + b"data: [DONE]\n\n"
        return httpx.Response(200, content=content, headers={"content-type": "text/event-stream"})

    provider_client = httpx.AsyncClient(transport=httpx.MockTransport(provider))
    app = create_app(provider_url="http://provider/generate", client=provider_client)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway"
        ) as gateway:
            response = await gateway.post("/v1/generate", json={"prompt": "hello"})
    assert response.status_code == 200
    deltas = []
    for line in response.text.splitlines():
        if line.startswith("data: {"):
            deltas.append(json.loads(line[6:]).get("delta", ""))
    joined = "".join(deltas)
    assert joined == "Reach [REDACTED] and [REDACTED] now."
    assert "example.com" not in response.text

