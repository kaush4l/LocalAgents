"""
Chrome Agent - Specialized agent for browser automation using Chrome DevTools MCP.
"""
import logging
import asyncio
from core.tools import get_mcp_toolkit, format_tool_for_engine
from core.engine import ReActContext
from core.responses import ReActResponse
from core import config

logger = logging.getLogger(__name__)


async def _setup_chrome_agent():
    """
    Async setup function for Chrome agent with Chrome DevTools MCP server.
    """
    # Configuration for Chrome DevTools MCP server
    server_config = {
        "command": "npx",
        "args": ["-y", "chrome-devtools-mcp", "--isolated"]
    }
    
    toolkit = get_mcp_toolkit(server_config)
    logger.info("Initializing Chrome MCP Toolkit...")
    
    try:
        await toolkit.initialize()
    except Exception as e:
        logger.warning(f"Could not connect to Chrome MCP server: {e}")
    
    # Selected subset of tools for Chrome
    selected_names = ["navigate_page", "take_screenshot", "click", "evaluate_script"]
    selected_tools_raw = toolkit.get_tools(selected_names)
    
    if not selected_tools_raw and toolkit._tools:
        available = [t.name for t in toolkit._tools]
        logger.warning(f"None of {selected_names} found in server tools. Available: {available}")
    
    # Format tools for the engine
    formatted_tools = [format_tool_for_engine(t) for t in selected_tools_raw]
    
    # Create the agent context
    agent = ReActContext(
        name="chrome_agent",
        description="An agent capable of controlling a browser via Chrome DevTools.",
        system_instructions="chrome_agent",
        model_id=config.MODEL_ID,
        tools=formatted_tools,
        response_model=ReActResponse,
        response_format='toon',
    )
    
    # Set the MCP toolkit for this agent's MCP tools
    agent.set_mcp_toolkit(toolkit)

    # Register cleanup for the toolkit
    if toolkit:
        agent.register_cleanup(toolkit.close)
    
    return agent


# Initialize chrome_agent at module import time
try:
    chrome_agent = asyncio.run(_setup_chrome_agent())
except Exception as e:
    logger.error(f"Failed to initialize chrome_agent: {e}")
    # Create a minimal agent on failure
    chrome_agent = ReActContext(
        name="chrome_agent",
        description="An agent capable of controlling a browser via Chrome DevTools.",
        system_instructions="chrome_agent",
        model_id=config.MODEL_ID,
        tools=[],
        response_model=ReActResponse,
        response_format='toon',
    )
