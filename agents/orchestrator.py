"""
Orchestrator Agent — the central coordinator.

Imports all sub-agents directly and wires them as tools.
"""

from __future__ import annotations

from agents.sub_agents.command_line_agent import command_line_agent
from agents.sub_agents.self_agent import self_agent
from agents.sub_agents.web_search_agent import web_search_agent
from core.engine import ReActAgent

# Module-level singleton — populated by ``build_orchestrator()``
orchestrator: ReActAgent | None = None

# All sub-agents available to the orchestrator
_SUB_AGENTS = [
    command_line_agent,
    web_search_agent,
    self_agent,
]


def build_orchestrator() -> ReActAgent:
    """Build (or rebuild) the orchestrator with all sub-agents."""
    global orchestrator

    orchestrator = ReActAgent(
        name="orchestrator",
        description="The main assistant that coordinates and delegates tasks to specialized agents.",
        system_instructions="orchestrator",
        tools=list(_SUB_AGENTS),
    )
    return orchestrator
