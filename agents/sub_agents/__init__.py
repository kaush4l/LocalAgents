"""
Sub-agents package — specialized agents delegated to by the orchestrator.

Each sub-agent file exports a module-level singleton (synchronous agents)
or an async factory function (agents that need runtime init, e.g. chrome).
"""

from .command_line_agent import command_line_agent
from .web_search_agent import web_search_agent

__all__ = [
    "command_line_agent",
    "web_search_agent",
]
