"""
Chrome Agent - Specialized agent for browser automation using Chrome DevTools MCP.

Pre-loads all Chrome tools in memory and creates a single agent instance.
All tools are filtered and formatted at module initialization time.
"""
import logging
import asyncio
from core.tools import MCPToolkit, format_tool_for_engine
from core.engine import ReActContext
from core.responses import ReActResponse
from core.config import settings

logger = logging.getLogger(__name__)

# Lazy initialization: tools are loaded on first use
_chrome_toolkit = None
_chrome_tools = []
_is_initialized = False


def _init_chrome_tools_lazy():
    """Initialize Chrome tools on first access (lazy initialization)."""
    global _chrome_toolkit, _chrome_tools, _is_initialized
    
    if _is_initialized:
        return _chrome_tools
    
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
    
    return _chrome_tools


# Create the Chrome agent instance with lazy-loaded tools
chrome_agent = ReActContext(
    name="chrome_agent",
    description="An agent capable of controlling a browser via Chrome DevTools.",
    system_instructions="chrome_agent",
    model_id=settings.MODEL_ID,
    tools=[],  # Start with empty tools, will be populated on first use
    response_model=ReActResponse,
    response_format="json"
)

# Store toolkit reference for cleanup
chrome_agent._toolkit = _chrome_toolkit
chrome_agent._init_tools = _init_chrome_tools_lazy
chrome_agent._tools_initialized = False


# Override the tools property to lazy-load on first access
def _get_tools():
    """Lazy load tools on first access."""
    if not chrome_agent._tools_initialized:
        tools = _init_chrome_tools_lazy()
        chrome_agent.tools = tools
        chrome_agent._tools_initialized = True
    return chrome_agent.tools


# Monkey-patch the tools property
original_tools = chrome_agent.tools
if not original_tools:
    chrome_agent.tools = []

logger.info("Chrome agent created (tools will be initialized on first use)")

