"""Chrome Agent - Specialized agent for browser automation using Chrome DevTools MCP."""
import logging
import asyncio

from core.tools import get_mcp_toolkit, format_tool_for_engine
from core.engine import ReActContext
from core.responses import ReActResponse
from core import config

logger = logging.getLogger(__name__)


async def _setup_chrome_agent():
    """Async setup that connects to an MCP server and builds the agent."""
    server_config = {
        "command": "npx",
        "args": ["-y", "chrome-devtools-mcp", "--isolated"]
    }

    toolkit = get_mcp_toolkit(server_config)
    logger.info("Initializing Chrome MCP Toolkit...")
    await toolkit.initialize()

    # Pick a small set of useful browser tools
    selected_names = ["navigate_page", "take_screenshot", "click", "evaluate_script"]
    selected_tools_raw = toolkit.get_tools(selected_names)
    if not selected_tools_raw and toolkit._tools:
        available = [t.name for t in toolkit._tools]
        logger.warning(f"Selected chrome tools {selected_names} not found. Available: {available}")

    formatted_tools = [format_tool_for_engine(t) for t in selected_tools_raw]

    agent = ReActContext(
        name="chrome_agent",
        description="An agent capable of controlling a browser via Chrome DevTools.",
        system_instructions="chrome_agent",
        model_id=config.MODEL_ID,
        tools=formatted_tools,
        response_model=ReActResponse,
        response_format="toon",
    )

    agent.set_mcp_toolkit(toolkit)
    agent.register_cleanup(toolkit.close)
    return agent


# Initialize the chrome_agent on import.
# In this project we prefer failing fast on misconfiguration.
chrome_agent = asyncio.run(_setup_chrome_agent())
