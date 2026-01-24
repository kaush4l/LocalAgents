"""
Team module for AppleShortcuts multi-agent runtime.

This package contains specialized agent implementations:
- CommandLineAgent: Shell command execution
- ChromeAgent: Browser automation via MCP Chrome DevTools
"""

from team.command_line_agent import initialize_command_line_agent
from team.chrome_agent import initialize_chrome_agent

__all__ = [
    "initialize_command_line_agent",
    "initialize_chrome_agent",
]
