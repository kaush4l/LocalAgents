"""
Agent definitions for the multi-agent workflow system.

All agents are pre-initialized instances, available immediately on import.
"""
from .command_line_agent import command_line_agent
from .chrome_agent import chrome_agent
from .orchestrator import orchestrator, close_orchestrator

__all__ = [
    "command_line_agent",
    "chrome_agent",
    "orchestrator",
    "close_orchestrator",
]
