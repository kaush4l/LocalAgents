"""
Self Agent — personal habit tracking assistant for the /self page.

This is a standalone workflow, not part of the orchestrator.
Tools operate on PostgreSQL via the db layer.
"""

from __future__ import annotations

from core.engine import ReActAgent
from workflows.self.tools import add_habit, remove_habit, check_habit, get_self_status

tools = [add_habit, remove_habit, check_habit, get_self_status]

# Module-level singleton
self_agent: ReActAgent | None = None


def build_self_agent() -> ReActAgent:
    """Build (or rebuild) the self agent."""
    global self_agent

    self_agent = ReActAgent(
        name="self_agent",
        description=(
            "Personal habit tracking assistant.\n"
            "\n"
            "Best for:\n"
            "- Adding or removing habits to track\n"
            "- Marking habits as done for today\n"
            "- Checking today's progress and completion status\n"
            "\n"
            "Tools: add_habit, remove_habit, check_habit, get_self_status"
        ),
        system_instructions="self_agent",
        tools=tools,
        max_iterations=3,
    )
    return self_agent
