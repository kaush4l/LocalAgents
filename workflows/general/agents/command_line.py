"""
Command Line Agent — executes safe shell commands.

Tools are declared, initialized, and ready at module level.
The ``command_line_agent`` instance is importable and ready to invoke.
"""

from __future__ import annotations

import re
import shlex
import subprocess

from core.engine import ReActAgent

# ── safety filters ───────────────────────────────────────────────────────────

_BLACKLIST_PATTERNS = [
    r"\brm\s+-rf\b",
    r"\bdd\b",
    r"\bmkfs\b",
    r"\bformat\b",
    r"\bshutdown\b|\breboot\b|\bhalt\b",
    r":",  # fork-bomb
]
_BLACKLIST_RE = [re.compile(p, re.IGNORECASE) for p in _BLACKLIST_PATTERNS]


# ── tool ─────────────────────────────────────────────────────────────────────


def execute_command(inputs: dict) -> str:
    """Execute a shell command after safety filtering.

    Args:
        inputs: Dict with keys:
            - command (str): The command to execute
            - cwd (str, optional): Working directory
            - timeout (int, optional): Timeout in seconds (default 10)
            - allow_sudo (bool, optional): Allow sudo (default False)

    Returns:
        Command output or error/safety message.
    """
    command = (inputs.get("command") or inputs.get("inputs") or inputs.get("query") or "").strip()
    cwd = inputs.get("cwd")
    timeout = inputs.get("timeout", 10)
    allow_sudo = inputs.get("allow_sudo", False)

    try:
        argv = shlex.split(command)
    except Exception:
        argv = [command]

    if any(tok.lower() == "sudo" for tok in argv) and not allow_sudo:
        return "unsafe to run"

    for rx in _BLACKLIST_RE:
        if rx.search(command):
            return "unsafe to run"

    try:
        proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, shell=False)
        result = proc.stdout or proc.stderr or ""
        if len(result) > 4000:
            result = result[:4000] + "\n...[truncated]"
        return result
    except subprocess.TimeoutExpired:
        return "Command timed out"
    except FileNotFoundError:
        return f"Command not found: {argv[0] if argv else command}"
    except Exception as e:
        return f"Error: {e}"


# ── agent instance ───────────────────────────────────────────────────────────

tools = [execute_command]

command_line_agent = ReActAgent(
    name="command_line_agent",
    description=(
        "Executes safe, non-interactive shell commands on the local machine.\n"
        "\n"
        "Best for:\n"
        "- Inspecting the repo (list files, read config, search text)\n"
        "- Running quick dev commands (format/lint/test/build) when safe\n"
        "- Collecting local environment facts (versions, paths, process info)\n"
        "\n"
        "Safety: blocks sudo, rm -rf, dd, mkfs, fork-bombs. Output truncated ~4k chars.\n"
        "\n"
        'Primary tool: execute_command({"command": "...", "cwd": "...", "timeout": 10})'
    ),
    system_instructions="command_line_agent",
    tools=tools,
)
