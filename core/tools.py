"""
Tool functions for the agent system.
Provides command line execution and other utility tools.
"""
import asyncio
import logging
import os
import subprocess
from typing import Optional
from fastmcp import Client

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
        
        # FastMCP Client expects a config.
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
        
        selected = [t for t in self._tools if t.name in selected_tool_names]
        if not selected and self._tools:
            logger.warning(f"Selected tools {selected_tool_names} not found. Available: {[t.name for t in self._tools]}")
        return selected

    async def call_tool(self, name: str, arguments: dict):
        """Call a specific tool."""
        if not self.client:
            logger.error("Toolkit not initialized when calling tool")
            return "Error: Toolkit not initialized. Call initialize() first."
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
    schema = getattr(mcp_tool, "input_schema", {})
    if hasattr(schema, "model_dump"):
        schema = schema.model_dump()
    
    properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
    params_list = []
    
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
        "mcp_tool": mcp_tool
    }


def get_mcp_toolkit(server_config: dict):
    return MCPToolkit(server_config)


async def execute_command(command: str, timeout: int = 60) -> str:
    """Execute a shell command on the local system safely and return its output.
    
    Args:
        command: The shell command to execute
        timeout: Maximum time in seconds to wait for the command (default: 60)
    
    Returns:
        A string containing STDOUT, STDERR, and execution status
    
    Examples:
        execute_command({"command": "ls -la"})
        execute_command({"command": "echo 'Hello World'"})
        execute_command({"command": "pwd"})
    """
    logger.info(f"Executing command: {command}")
    
    # Security: Block obviously dangerous commands
    dangerous_patterns = ['rm -rf /', 'mkfs', ':(){', 'fork bomb', '> /dev/sda']
    for pattern in dangerous_patterns:
        if pattern in command.lower():
            return f"Error: Dangerous command pattern detected: {pattern}"
    
    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=os.getcwd()
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            process.kill()
            return f"Error: Command timed out after {timeout} seconds"
        
        output = stdout.decode(errors="replace").strip()
        error = stderr.decode(errors="replace").strip()
        
        parts = []
        if output:
            parts.append(f"STDOUT:\n{output}")
        if error:
            parts.append(f"STDERR:\n{error}")
        if process.returncode != 0:
            parts.append(f"EXIT CODE: {process.returncode}")
        
        result = "\n\n".join(parts) if parts else "Command executed successfully (no output)."
        logger.debug(f"Command completed: {result[:100]}...")
        return result
        
    except Exception as e:
        logger.error(f"Command execution failed: {type(e).__name__}: {e}")
        return f"Error executing command: {e}"


def execute_command_sync(command: str, timeout: int = 60) -> str:
    """Synchronous version of execute_command for non-async contexts."""
    logger.info(f"Executing command (sync): {command}")
    
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            timeout=timeout,
            cwd=os.getcwd()
        )
        
        output = result.stdout.decode(errors="replace").strip()
        error = result.stderr.decode(errors="replace").strip()
        
        parts = []
        if output:
            parts.append(f"STDOUT:\n{output}")
        if error:
            parts.append(f"STDERR:\n{error}")
        if result.returncode != 0:
            parts.append(f"EXIT CODE: {result.returncode}")
        
        return "\n\n".join(parts) if parts else "Command executed successfully (no output)."
        
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout} seconds"
    except Exception as e:
        return f"Error executing command: {e}"


async def read_file(path: str) -> str:
    """Read the contents of a file.
    
    Args:
        path: The path to the file to read
    
    Returns:
        The file contents or an error message
    """
    try:
        with open(path, 'r') as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {e}"


async def write_file(path: str, content: str) -> str:
    """Write content to a file.
    
    Args:
        path: The path to the file to write
        content: The content to write to the file
    
    Returns:
        A success message or error message
    """
    try:
        with open(path, 'w') as f:
            f.write(content)
        return f"Successfully wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error writing file: {e}"


async def list_directory(path: str = ".") -> str:
    """List contents of a directory.
    
    Args:
        path: The directory path to list (default: current directory)
    
    Returns:
        A formatted list of files and directories
    """
    try:
        entries = os.listdir(path)
        items = []
        for entry in sorted(entries):
            full_path = os.path.join(path, entry)
            if os.path.isdir(full_path):
                items.append(f"📁 {entry}/")
            else:
                size = os.path.getsize(full_path)
                items.append(f"📄 {entry} ({size} bytes)")
        return "\n".join(items) if items else "Directory is empty"
    except Exception as e:
        return f"Error listing directory: {e}"


# Tool registry for easy lookup
AVAILABLE_TOOLS = {
    "execute_command": execute_command,
    "read_file": read_file,
    "write_file": write_file,
    "list_directory": list_directory,
}


def get_tool(name: str):
    """Get a tool function by name."""
    return AVAILABLE_TOOLS.get(name)


def available_tools() -> list:
    """Return list of available tool names."""
    return list(AVAILABLE_TOOLS.keys())
