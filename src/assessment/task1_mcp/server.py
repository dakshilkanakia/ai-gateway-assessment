"""Official-SDK MCP server using stdio exclusively for protocol traffic."""

from __future__ import annotations

import logging
import sys
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp import types
from mcp.shared.exceptions import McpError
from pydantic import Field, ValidationError

from .service import (
    CustomerId,
    GetCustomerRecordInput,
    TriggerRefundInput,
    get_customer_record as lookup_customer,
    trigger_refund as create_refund,
)

# Explicit stderr handler prevents accidental protocol corruption on stdout.
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    force=True,
)
logger = logging.getLogger(__name__)
mcp = FastMCP("customer-service", log_level="WARNING")


@mcp.tool()
def get_customer_record(customer_id: CustomerId) -> dict[str, object]:
    """Return a customer record for an identifier formatted CUST-XXXXX."""
    data = GetCustomerRecordInput(customer_id=customer_id)
    logger.info("customer record requested for %s", data.customer_id)
    return lookup_customer(data)


@mcp.tool()
def trigger_refund(
    customer_id: CustomerId,
    amount: Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True)],
    reason: Annotated[str, Field(min_length=10)],
) -> dict[str, object]:
    """Submit a positive refund with a meaningful reason."""
    data = TriggerRefundInput(
        customer_id=customer_id,
        amount=amount,
        reason=reason,
    )
    logger.info("refund requested for %s", data.customer_id)
    return create_refund(data)


# FastMCP normally converts function validation failures into MCP tool results.
# This assessment explicitly asks for JSON-RPC invalid-params errors, so wrap the
# official SDK's registered handler and map schema failures to -32602 before the
# tool executes. All framing/session/transport behavior remains SDK-owned.
_sdk_call_tool_handler = mcp._mcp_server.request_handlers[types.CallToolRequest]


async def _strict_call_tool_handler(request: types.CallToolRequest) -> types.ServerResult:
    arguments = request.params.arguments or {}
    model = {
        "get_customer_record": GetCustomerRecordInput,
        "trigger_refund": TriggerRefundInput,
    }.get(request.params.name)
    if model is not None:
        try:
            model.model_validate(arguments)
        except ValidationError as error:
            locations = [".".join(str(part) for part in item["loc"]) for item in error.errors()]
            raise McpError(
                types.ErrorData(
                    code=types.INVALID_PARAMS,
                    message="Invalid tool arguments",
                    data={"fields": locations},
                )
            ) from None
    return await _sdk_call_tool_handler(request)


mcp._mcp_server.request_handlers[types.CallToolRequest] = _strict_call_tool_handler


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
