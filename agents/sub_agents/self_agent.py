"""
Self Agent — personal habit tracking assistant for the /self page.

Tools operate on app_state.habits and app_state.checkins (server-side state).
Imports of app.state are lazy (inside tool function bodies) to respect the
agents/ → app/ layering rule: agents may not import app at module load time.
"""

from __future__ import annotations

from typing import Any

from core.engine import ReActAgent


def add_habit(inputs: dict[str, Any]) -> str:
    """Add a new habit to the tracking list.

    Args:
        inputs: {"name": "habit name"}
    """
    from app.state import app_state  # lazy import — kept inside function

    name = (inputs.get("name") or "").strip()
    if not name:
        return "Error: habit name is required."

    # Check for duplicates (case-insensitive)
    existing = [h for h in app_state.habits if h.get("name", "").strip().lower() == name.lower()]
    if existing:
        return f"'{name}' is already in your habits list."

    habit = app_state.add_habit(name)
    return f"Added '{habit['name']}' to your habits."


def remove_habit(inputs: dict[str, Any]) -> str:
    """Remove a habit from the tracking list.

    Args:
        inputs: {"name": "habit name"} or {"id": "habit_id"}
    """
    from app.state import app_state  # lazy import

    habit_id = (inputs.get("id") or inputs.get("habit_id") or "").strip() or None
    name = (inputs.get("name") or "").strip() or None

    if not habit_id and not name:
        return "Error: provide either 'name' or 'id' to remove a habit."

    removed = app_state.remove_habit(habit_id=habit_id, name=name)
    if removed:
        label = name or habit_id
        return f"Removed '{label}' from your habits."
    label = name or habit_id
    return f"No habit named '{label}' was found."


def check_habit(inputs: dict[str, Any]) -> str:
    """Mark a habit as done (or undone) for today or a given date.

    Args:
        inputs: {
            "name": "habit name",   # or "id": "habit_id"
            "done": true,           # optional, default true
            "date": "YYYY-MM-DD"    # optional, default today
        }
    """
    from app.state import app_state  # lazy import

    habit_id = (inputs.get("id") or inputs.get("habit_id") or "").strip() or None
    name = (inputs.get("name") or "").strip() or None
    date = (inputs.get("date") or "").strip() or None
    done_raw = inputs.get("done", True)
    done = done_raw if isinstance(done_raw, bool) else str(done_raw).lower() not in ("false", "0", "no")

    if not habit_id and not name:
        return "Error: provide either 'name' or 'id' to check a habit."

    success = app_state.check_habit(habit_id=habit_id, name=name, date=date, done=done)
    if not success:
        label = name or habit_id
        return f"No habit named '{label}' was found. Use add_habit first."

    label = name or habit_id
    action = "complete" if done else "incomplete"
    return f"Marked '{label}' as {action} for today."


def get_self_status(inputs: dict[str, Any]) -> str:  # noqa: ARG001
    """Get today's habits with their completion status and streak info.

    Args:
        inputs: {} (no parameters needed)
    """
    from app.state import app_state  # lazy import

    self_state = app_state.get_self_state()
    habits = self_state["habits"]
    today_checks = self_state["today_checks"]
    today = self_state["today"]

    if not habits:
        return "You have no habits set up yet. Add some with add_habit."

    done_habits = [h for h in habits if today_checks.get(h["id"])]
    pending = [h for h in habits if not today_checks.get(h["id"])]

    lines = [f"Today ({today}): {len(done_habits)}/{len(habits)} habits complete."]
    if done_habits:
        done_names = ", ".join(h["name"] for h in done_habits)
        lines.append(f"Done: {done_names}.")
    if pending:
        pending_names = ", ".join(h["name"] for h in pending)
        lines.append(f"Remaining: {pending_names}.")

    return " ".join(lines)


tools = [add_habit, remove_habit, check_habit, get_self_status]

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
)
