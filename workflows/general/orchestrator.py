"""
Orchestrator Agent — the central coordinator for the general workflow.

Imports all sub-agents directly and wires them as tools.
Self agent is NOT included here — it lives in workflows/self/.
"""

from __future__ import annotations

from workflows.general.agents.command_line import command_line_agent
from workflows.general.agents.web_search import web_search_agent
from core.engine import ReActAgent

# Module-level singleton — populated by ``build_orchestrator()``
orchestrator: ReActAgent | None = None

# All sub-agents available to the orchestrator
_SUB_AGENTS = [
    command_line_agent,
    web_search_agent,
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
