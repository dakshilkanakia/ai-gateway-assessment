from __future__ import annotations

import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import McpError


@pytest.mark.asyncio
async def test_real_stdio_transport_and_jsonrpc_validation() -> None:
    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", "assessment.task1_mcp.server"],
    )
    # The official client would fail decoding if a log line leaked to stdout.
    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert {tool.name for tool in tools.tools} == {
                "get_customer_record",
                "trigger_refund",
            }

            valid = await session.call_tool(
                "get_customer_record", {"customer_id": "CUST-A1B2C"}
            )
            assert not valid.isError
            assert valid.structuredContent["status"] == "active"

            with pytest.raises(McpError) as captured:
                await session.call_tool(
                    "trigger_refund",
                    {"customer_id": "BAD", "amount": -1.0, "reason": "short"},
                )
            assert captured.value.error.code == -32602
            assert captured.value.error.message == "Invalid tool arguments"
