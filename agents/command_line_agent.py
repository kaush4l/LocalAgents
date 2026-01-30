"""
Command Line Agent - Specialized agent for executing shell commands.

Pre-loads all command line tools in memory and creates a single agent instance.
All tools are included at module initialization time.
"""
from core.engine import ReActContext
from core.responses import ReActResponse
from core import config
from core.tools import execute_command


# Define tools for this agent (pre-loaded in memory)
tools = [execute_command]

# Create the Command Line agent instance with all tools pre-loaded
command_line_agent = ReActContext(
    name="command_line_agent",
    description="An agent capable of executing shell commands and managing files on the local system.",
    system_instructions="command_line_agent",
    model_id=config.MODEL_ID,
    tools=tools,
    response_model=ReActResponse,
    response_format="toon",
    max_iterations=config.MAX_ITERATIONS,
)
