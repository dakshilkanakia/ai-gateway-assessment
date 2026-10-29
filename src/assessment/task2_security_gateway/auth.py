"""Minimal bearer-token decoder for the assessment.

Tokens are configured as ``token:role`` pairs instead of pretending an unsigned
JWT is secure. Production deployments should inject a verified OIDC/JWT adapter.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header, HTTPException


@dataclass(frozen=True)
class Principal:
    token: str
    role: str


class TokenAuthenticator:
    def __init__(self, tokens: dict[str, str]) -> None:
        self._tokens = tokens

    def authenticate(self, authorization: str | None) -> Principal:
        scheme, separator, token = (authorization or "").partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not token:
            raise HTTPException(status_code=401, detail="Missing or invalid bearer token")
        role = self._tokens.get(token)
        if role is None:
            raise HTTPException(status_code=401, detail="Invalid bearer token")
        return Principal(token=token, role=role)


def bearer_header(authorization: str | None = Header(default=None)) -> str | None:
    return authorization

