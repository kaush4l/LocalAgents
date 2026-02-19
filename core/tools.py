"""
MCP tool initialization and wrapping.

Single public API:
    ``initialize_mcp_tools(server_config, tool_names)`` → ``(callables, client)``
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from fastmcp import Client

logger = logging.getLogger(__name__)


async def initialize_mcp_tools(
    server_config: dict[str, Any],
    tool_names: list[str],
) -> tuple[list[Callable], Client | None]:
    """Connect to an MCP server, filter tools, and return wrapped callables.

    Each returned callable has signature ``func(inputs: dict) -> str``.
    """
    command = server_config.get("command")
    args = server_config.get("args", [])
    if not command:
        raise ValueError("server_config must contain 'command' key")

    config = {"mcpServers": {"server": {"command": command, "args": args}}}
    client = Client(config)
    await client.__aenter__()
    all_tools = await client.list_tools()
    logger.info("MCP toolkit initialized with %d tools available", len(all_tools))

    available = {getattr(t, "name", None) for t in all_tools if hasattr(t, "name")}
    missing = set(tool_names) - available
    if missing:
        logger.warning("Requested tools not found: %s. Available: %s", missing, available)
    selected = [t for t in all_tools if getattr(t, "name", None) in tool_names]

    wrapped: list[Callable] = []
    for tool in selected:
        tool_name = tool.name

        async def _fn(inputs: dict, name: str = tool_name, mcp_client: Client = client) -> str:
            try:
                result = await mcp_client.call_tool(name, inputs)
                if hasattr(result, "content"):
                    return "\n".join(c.text for c in result.content if hasattr(c, "text"))
                return str(result)
            except Exception as e:
                return f"Error calling {name}: {e}"

        _fn.__name__ = tool_name
        _fn.__doc__ = getattr(tool, "description", "MCP tool")
        wrapped.append(_fn)

    return wrapped, client
