"""Boundary-safe, bounded-memory streaming PII redaction."""

from __future__ import annotations

import re

REDACTED = "[REDACTED]"

# Intentionally bounded to real-world field lengths so carry-over can be bounded.
EMAIL_RE = re.compile(
    r"(?<![\w.+-])[A-Z0-9._%+-]{1,64}@[A-Z0-9-]{1,63}"
    r"(?:\.[A-Z0-9-]{1,63})+(?![\w.-])",
    re.IGNORECASE,
)
SSN_RE = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")


def redact_pii(text: str) -> str:
    """Redact supported PII patterns in a complete piece of text."""
    text = EMAIL_RE.sub(REDACTED, text)
    text = SSN_RE.sub(REDACTED, text)
    return CARD_RE.sub(REDACTED, text)


class StreamingRedactor:
    """Hold only the potentially incomplete final token between chunks.

    Whitespace completes a token and makes it safe to inspect and emit. The
    256-character overlap covers the maximum supported email representation;
    it also prevents an adversarial unbroken token from growing memory forever.
    """

    def __init__(self, max_carry: int = 256) -> None:
        self._pending = ""
        self._max_carry = max_carry

    @property
    def pending_size(self) -> int:
        return len(self._pending)

    def feed(self, chunk: str) -> str:
        if not chunk:
            return ""
        self._pending += chunk

        whitespace = list(re.finditer(r"\s+", self._pending))
        if whitespace:
            cut = whitespace[-1].end()
        else:
            cut = max(0, len(self._pending) - self._max_carry)

        if cut == 0:
            return ""
        ready, self._pending = self._pending[:cut], self._pending[cut:]
        return redact_pii(ready)

    def flush(self) -> str:
        ready, self._pending = self._pending, ""
        return redact_pii(ready)

