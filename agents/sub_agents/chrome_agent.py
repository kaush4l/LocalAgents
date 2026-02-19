"""
Chrome Agent — browser automation via Chrome DevTools MCP.

MCP tools are initialized at startup via ``create_chrome_agent()``.
"""

from __future__ import annotations

from core.engine import ReActAgent
from core.logging_core import log_info
from core.tools import initialize_mcp_tools

# Chrome DevTools MCP Server Configuration
SERVER_CONFIG = {
    "command": "npx",
    "args": [
        "-y",
        "chrome-devtools-mcp",
        "--isolated",
        "--no-usage-statistics",
        "--headless=false",
        "--viewport=1280x720",
    ],
}

PRIMARY_TOOLS = [
    "navigate_page",
    "take_screenshot",
    "click",
    "evaluate_script",
    "take_snapshot",
]


async def create_chrome_agent() -> ReActAgent:
    """Async factory — initializes MCP tools, returns a ready agent."""
    wrapped_tools, _client = await initialize_mcp_tools(SERVER_CONFIG, PRIMARY_TOOLS)

    agent = ReActAgent(
        name="chrome_agent",
        description=(
            "Browser automation agent using Chrome DevTools.\n"
            "\n"
            "Best for:\n"
            "- Navigating web pages and taking screenshots\n"
            "- Clicking elements and filling forms\n"
            "- Running JavaScript in the browser\n"
            "- Web scraping and data extraction\n"
            "\n"
            "Tools: navigate_page, take_screenshot, click, evaluate_script, take_snapshot"
        ),
        system_instructions="chrome_agent",
        tools=wrapped_tools,
    )
    log_info(__name__, "Chrome agent initialized with %d tools", len(wrapped_tools))
    return agent
