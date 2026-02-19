"""
Agent definitions — orchestrator + sub-agents.
"""

from .orchestrator import orchestrator
from .sub_agents.command_line_agent import command_line_agent
from .sub_agents.web_search_agent import web_search_agent

__all__ = [
    "command_line_agent",
    "web_search_agent",
    "orchestrator",
]
