"""
Chrome Agent - Specialized agent for browser automation using Chrome DevTools MCP.

This module initializes a `chrome_agent` ReActContext via an async setup
function which connects to a local MCP server (via `get_mcp_toolkit`) and
registers a small set of browser control tools.

If initialization fails the module falls back to a minimal `chrome_agent`
instance with no tools so the rest of the system can still import it.
"""
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
    try:
        await toolkit.initialize()
    except Exception as e:
        logger.error(f"Failed to initialize MCP toolkit: {e}")
        raise

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


# Initialize the chrome_agent on import if possible, otherwise fallback
try:
    chrome_agent = asyncio.run(_setup_chrome_agent())
except Exception:
    logger.exception("Chrome agent initialization failed; creating fallback agent")
    chrome_agent = ReActContext(
        name="chrome_agent",
        description="An agent capable of controlling a browser via Chrome DevTools.",
        system_instructions="chrome_agent",
        model_id=config.MODEL_ID,
        tools=[],
        response_model=ReActResponse,
        response_format="toon",
    )
"""
Chrome Agent - Specialized agent for browser automation using Chrome DevTools MCP.

Pre-loads all Chrome tools in memory and creates a single agent instance.
All tools are filtered and formatted at module initialization time.
"""
import logging
import asyncio
<<<<<<< HEAD
from core.tools import get_mcp_toolkit, format_tool_for_engine
=======
from core.tools import get_mcp_toolkit, format_tool_for_engine
>>>>>>> wip/save-local-20260129-235217
from core.engine import ReActContext
from core.responses import ReActResponse
from core import config

logger = logging.getLogger(__name__)

# Lazy initialization: tools are loaded on first use
_chrome_toolkit = None
_chrome_tools = []
_is_initialized = False

<<<<<<< HEAD
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
=======

def _init_chrome_tools_lazy():
    """Initialize Chrome tools on first access (lazy initialization)."""
    global _chrome_toolkit, _chrome_tools, _is_initialized
    
    if _is_initialized:
        return _chrome_tools
>>>>>>> wip/save-local-20260129-235217
    
    try:
        logger.info("Initializing Chrome MCP toolkit...")
        
        # Configuration for Chrome DevTools MCP server
        server_config = {
            "command": "npx",
            "args": ["-y", "chrome-devtools-mcp", "--isolated"]
        }
        
        _chrome_toolkit = MCPToolkit(server_config)
        
        # Run async initialization
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(_chrome_toolkit.initialize())
            loop.close()
        except Exception as e:
            logger.warning(f"Could not initialize MCP event loop: {e}")
            # Try to use existing event loop
            try:
                asyncio.run(_chrome_toolkit.initialize())
            except Exception as e2:
                logger.error(f"Failed to initialize Chrome MCP: {e2}")
                _is_initialized = True
                return []
        
        # Selected subset of tools for Chrome (filtered upfront)
        selected_names = ["navigate_page", "take_screenshot", "click", "evaluate_script"]
        selected_tools_raw = _chrome_toolkit.get_tools(selected_names)
        
        if not selected_tools_raw and _chrome_toolkit._tools:
            available = [t.name for t in _chrome_toolkit._tools]
            logger.warning(f"Selected chrome tools {selected_names} not found. Available: {available}")
        
        # Format tools for the engine
        _chrome_tools = [format_tool_for_engine(t) for t in selected_tools_raw]
        _is_initialized = True
        logger.info(f"Chrome agent initialized with {len(_chrome_tools)} tools")
        
    except Exception as e:
        logger.error(f"Failed to initialize Chrome toolkit: {e}")
        _is_initialized = True
    
<<<<<<< HEAD
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
    _chrome_toolkit = None
    _chrome_tools = []
    _is_initialized = False

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
