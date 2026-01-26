"""
Command Line Agent - Specialized agent for executing shell commands.
"""
from core.engine import ReActContext
from core.responses import ReActResponse
from core.config import settings
from core.tools import execute_command


class CommandLineAgent(ReActContext):
    """An agent specialized in executing shell commands and file operations."""
    
    def __init__(self, **kwargs):
        defaults = {
            "name": "CommandLineAgent",
            "description": "An agent capable of executing shell commands and managing files on the local system.",
            "system_instructions": "command_line_agent",
            "model_id": settings.MODEL_ID,
            "tools": [execute_command],
            "response_model": ReActResponse,
            "response_format": "json",
            "max_iterations": settings.MAX_ITERATIONS,
        }
        defaults.update(kwargs)
        super().__init__(**defaults)


async def initialize_command_line_agent() -> CommandLineAgent:
    """Initialize and return a CommandLineAgent instance."""
    agent = CommandLineAgent()
    return agent
