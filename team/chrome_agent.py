import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from core.tools import get_mcp_toolkit, format_tool_for_engine
from core.engine import ReActContext
from core.responses import ReActResponse
from core.config import DEFAULT_MODEL_ID

async def initialize_chrome_agent():
    # Configuration for Chrome DevTools MCP server
    server_config = {
        "command": "npx",
        "args": ["-y", "chrome-devtools-mcp", "--isolated"]
    }
    
    toolkit = get_mcp_toolkit(server_config)
    print("Initializing MCP Toolkit...")
    try:
        await toolkit.initialize()
    except Exception as e:
        print(f"Warning: Could not connect to MCP server during init: {e}")
    
    # Selected subset of tools
    selected_names = ["navigate_page", "take_screenshot", "click", "evaluate_script"]
    selected_tools_raw = toolkit.get_tools(selected_names)
    
    if not selected_tools_raw and toolkit._tools:
        print(f"Warning: None of {selected_names} found in server tools: {[t.name for t in toolkit._tools]}")
    
    # Format tools for the engine
    formatted_tools = [format_tool_for_engine(t) for t in selected_tools_raw]
    
    # Create the agent context
    agent = ReActContext(
        name="ChromeAgent",
        description="An agent capable of controlling a browser via Chrome DevTools.",
        system_instructions="chrome_agent",
        model_id=DEFAULT_MODEL_ID,
        tools=formatted_tools,
        toolkit=toolkit,
        response_model=ReActResponse,
        response_format='json'
    )
    
    return agent, toolkit

async def main():
    agent, toolkit = await initialize_chrome_agent()
    
    try:
        query = "Navigate to google.com and tell me the title of the page."
        print(f"User: {query}")
        
        result = await agent.invoke(query)
        print(f"\nMission: {result.rephrase}")
        print(f"Strategy: {result.reverse}")
        print(f"Action: {result.action}")
        print(f"Final Answer: {result.answer}")
        
    finally:
        await toolkit.close()

if __name__ == "__main__":
    asyncio.run(main())
