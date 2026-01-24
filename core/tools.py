from fastmcp import Client
import asyncio
import os
import logging

logger = logging.getLogger(__name__)

class MCPToolkit:
    def __init__(self, server_config: dict):
        self.server_config = server_config
        self.client = None
        self._tools = []
        self.last_error = None

    async def initialize(self):
        """Initialize the MCP client and fetch tools."""
        command = self.server_config.get("command")
        args = self.server_config.get("args", [])
        
        # FastMCP 3.0 Client expects a transport or config.
        # We can pass an MCP config dict.
        config = {
            "mcpServers": {
                "server": {
                    "command": command,
                    "args": args
                }
            }
        }
        
        try:
            logger.info(f"Initializing MCP toolkit with command: {command} {' '.join(args)}")
            self.client = Client(config)
            await self.client.__aenter__()
            available_tools = await self.client.list_tools()
            self._tools = available_tools
            logger.info(f"MCP toolkit initialized with {len(self._tools)} tools")
            return self._tools
        except Exception as e:
            self.last_error = str(e)
            self._tools = []
            logger.error(f"Failed to initialize MCP toolkit: {type(e).__name__}: {e}")
            return self._tools

    def get_tools(self, selected_tool_names: list = None):
        """Return a list of tools, optionally filtered by name."""
        if not selected_tool_names:
            return self._tools
        
        # In fastmcp 3.0, list_tools() returns Tool objects which might have .name
        selected = [t for t in self._tools if t.name in selected_tool_names]
        if not selected and self._tools:
            logger.warning(f"Selected tools {selected_tool_names} not found. Available: {[t.name for t in self._tools]}")
        return selected

    async def call_tool(self, name: str, arguments: dict):
        """Call a specific tool."""
        if not self.client:
            logger.error("Toolkit not initialized when calling tool")
            return "Error: Toolkit not initialized. Call initialize() first."
        # FastMCP 3.0 call_tool returns a Result object
        try:
            logger.debug(f"Calling tool: {name} with args: {arguments}")
            result = await self.client.call_tool(name, arguments)
            # Convert result to string for the engine's observation
            if hasattr(result, "content"):
                output = "\n".join([c.text for c in result.content if hasattr(c, "text")])
                logger.debug(f"Tool {name} returned: {output[:100]}...")
                return output
            logger.debug(f"Tool {name} returned: {str(result)[:100]}...")
            return str(result)
        except Exception as e:
            self.last_error = str(e)
            logger.error(f"Tool call failed for {name}: {type(e).__name__}: {e}")
            return f"Error calling tool {name}: {e}"

    async def close(self):
        if self.client:
            try:
                await self.client.__aexit__(None, None, None)
                logger.info("MCP toolkit closed successfully")
            except Exception as e:
                self.last_error = str(e)
                logger.error(f"Error closing MCP toolkit: {e}")

def format_tool_for_engine(mcp_tool):
    """Convert an MCP tool into the dictionary format expected by core/engine.py."""
    # MCP tool typically has .name, .description, and .input_schema
    schema = getattr(mcp_tool, "input_schema", {})
    if hasattr(schema, "model_dump"):
        schema = schema.model_dump()
    
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    params_list = []
    
    # Handle both dict and object schemas
    if not properties and hasattr(schema, "properties"):
        properties = schema.properties

    for p_name, p_info in properties.items():
        p_type = p_info.get("type", "Any") if isinstance(p_info, dict) else "Any"
        params_list.append(f"{p_name}: {p_type}")
    
    params_str = ", ".join(params_list)
    
    return {
        "name": mcp_tool.name,
        "description": mcp_tool.description,
        "parameters": params_str,
        "mcp_tool": mcp_tool # Keep reference for execution
    }

def get_mcp_toolkit(server_config: dict):
    return MCPToolkit(server_config)

async def execute_command(command: str) -> str:
    """Execute a shell command on the local system safely and return its output and errors."""
    import asyncio
    logger.debug(f"Executing command: {command}")
    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        output = stdout.decode().strip()
        error = stderr.decode().strip()

        parts = []
        if output:
            parts.append(f"STDOUT:\n{output}")
        if error:
            parts.append(f"STDERR:\n{error}")

        result = "\n\n".join(parts) if parts else "Command executed successfully (no output)."
        logger.debug(f"Command completed: {result[:100]}...")
        return result
    except Exception as e:
        logger.error(f"Command execution failed: {type(e).__name__}: {e}")
        return f"Error executing command: {e}"

if __name__ == "__main__":
    # Test connection
    async def test():
        config = {"command": "npx", "args": ["-y", "chrome-devtools-mcp"]}
        toolkit = get_mcp_toolkit(config)
        try:
            print("Connecting...")
            tools = await toolkit.initialize()
            print(f"Connected. Found {len(tools)} tools.")
            for t in tools:
                print(f" - {t.name}: {t.description[:60]}...")
        finally:
            await toolkit.close()
    
    asyncio.run(test())
