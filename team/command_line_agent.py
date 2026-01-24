import asyncio
import sys
import os
from pathlib import Path

# Add the project root to sys.path so we can import from core
project_root = str(Path(__file__).parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

from core.engine import ReActContext
from core.responses import ReActResponse
from core.config import DEFAULT_MODEL_ID
from core.tools import execute_command

async def initialize_command_line_agent():
    """Initialize the Command Line agent context."""
    
    # Create the agent context
    agent = ReActContext(
        name="CommandLineAgent",
        description="An agent capable of executing shell commands.",
        system_instructions="command_line_agent",
        model_id=DEFAULT_MODEL_ID,
        tools=[execute_command],
        response_model=ReActResponse,
        response_format='json'
    )
    
    return agent

async def main():
    agent = await initialize_command_line_agent()
    
    try:
        query = "List the files in the current directory and find out what is in pyproject.toml"
        print(f"User: {query}")
        
        result = await agent.invoke(query)
        print(f"\nMission: {result.rephrase}")
        print(f"Strategy: {result.reverse}")
        print(f"Action: {result.action}")
        print(f"Final Answer: {result.answer}")
                
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
