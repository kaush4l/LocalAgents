"""
Core module for AppleShortcuts multi-agent runtime.

This package provides the foundational abstractions:
- BaseContext / ReActContext: LLM context engines with prompt management
- BaseResponse / ReActResponse: Structured response models with parsing
- MCPToolkit: MCP server integration for external tools
- invoke: Sync-first LLM inference
"""

from core.engine import BaseContext, ReActContext, Message
from core.responses import BaseResponse, ReActResponse, ResponseFormat
from core.inference import invoke
from core.tools import MCPToolkit, format_tool_for_engine, execute_command, get_mcp_toolkit

__all__ = [
    # Engine
    "BaseContext",
    "ReActContext", 
    "Message",
    # Responses
    "BaseResponse",
    "ReActResponse",
    "ResponseFormat",
    # Inference
    "invoke",
    # Tools
    "MCPToolkit",
    "format_tool_for_engine",
    "execute_command",
    "get_mcp_toolkit",
]
