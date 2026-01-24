import sys
from pathlib import Path

# Add project root to path if needed (though usually handled by main)
sys.path.append(str(Path(__file__).parent.parent))

from core.engine import ReActContext
from core.responses import ReActResponse
from core.config import DEFAULT_MODEL_ID, DEFAULT_MAX_ITERATIONS
from team.command_line_agent import initialize_command_line_agent
from team.chrome_agent import initialize_chrome_agent
from core.logger import get_logger

logger = get_logger("Orchestrator")

async def initialize_orchestrator():
    """
    Initialize the Orchestrator agent (Alfred) and its worker agents.
    Returns: (orchestrator_context, chrome_toolkit)
    """
    logger.info("Initializing Orchestrator and sub-agents...")
    
    # Initialize workers
    logger.info("Initializing CommandLineAgent...")
    cli_agent = await initialize_command_line_agent()
    cli_agent.name = "CommandLineAgent"
    logger.info("CommandLineAgent initialized.")

    logger.info("Initializing ChromeAgent...")
    chrome_agent, chrome_toolkit = await initialize_chrome_agent()
    chrome_agent.name = "ChromeAgent"
    logger.info("ChromeAgent initialized.")

    # Initialize Orchestrator
    # The system instructions 'orchestrator' corresponds to prompts/orchestrator.md
    orchestrator = ReActContext(
        name="Orchestrator",
        description="The main assistant, Alfred, that delegates tasks to workers.",
        system_instructions="orchestrator",
        model_id=DEFAULT_MODEL_ID,
        tools=[cli_agent, chrome_agent],
        response_model=ReActResponse,
        response_format="json",
        max_iterations=DEFAULT_MAX_ITERATIONS
    )
    
    logger.info("Orchestrator initialized successfully.")
    
    # Log initialization report for debugging
    report = orchestrator.initialization_report()
    logger.debug(f"Orchestrator Configuration: {report}")
    
    return orchestrator, chrome_toolkit
