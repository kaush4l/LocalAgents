"""
Self workflow — standalone habit tracking agent.

Not part of the general orchestrator. This workflow runs independently
on the /self page with its own tools and agent.
"""

from .agent import self_agent, build_self_agent

__all__ = ["self_agent", "build_self_agent"]
