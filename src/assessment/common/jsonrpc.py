"""Small, typed JSON-RPC 2.0 helpers shared by the HTTP gateways."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class JsonRpcRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jsonrpc: str = Field(pattern=r"^2\.0$")
    id: str | int | None = None
    method: str
    params: dict[str, Any] | None = None


def error_response(
    request_id: str | int | None,
    code: int,
    message: str,
    data: Any | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}

