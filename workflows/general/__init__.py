"""
General workflow — orchestrator + sub-agents.

The orchestrator delegates to specialised agents for shell commands,
web search, and browser automation.
"""

from .orchestrator import build_orchestrator, orchestrator

__all__ = ["build_orchestrator", "orchestrator"]
