"""
Orchestrator Agent - The main coordinator that delegates tasks to specialized agents.
"""
import logging
from core.engine import ReActContext
from core.responses import ReActResponse
from core.config import settings
from .command_line_agent import initialize_command_line_agent
from .chrome_agent import initialize_chrome_agent

logger = logging.getLogger(__name__)


class Orchestrator(ReActContext):
    """The main orchestrator agent (Alfred) that coordinates tasks across sub-agents.
    
    This agent:
    1. Receives user requests
    2. Analyzes and breaks them down into tasks
    3. Delegates to appropriate specialized agents
    4. Synthesizes results into coherent responses
    """
    
    def __init__(self, sub_agents: list = None, **kwargs):
        self.toolkits = kwargs.pop("toolkits", [])
        defaults = {
            "name": "Orchestrator",
            "description": "The main assistant that coordinates and delegates tasks to specialized agents.",
            "system_instructions": "orchestrator",
            "model_id": settings.MODEL_ID,
            "tools": sub_agents or [],
            "response_model": ReActResponse,
            "response_format": "json",
            "max_iterations": settings.MAX_ITERATIONS,
        }
        defaults.update(kwargs)
        super().__init__(**defaults)

    async def close(self):
        """Close all toolkits and resources."""
        for toolkit in self.toolkits:
            try:
                await toolkit.close()
            except Exception as e:
                logger.error(f"Error closing toolkit: {e}")


async def initialize_orchestrator():
    """
    Initialize the Orchestrator agent and its worker agents.
    
    Returns:
        orchestrator: The main orchestrator context
    """
    logger.info("Initializing Orchestrator and sub-agents...")
    
    # Initialize workers
    logger.info("Initializing CommandLineAgent...")
    cli_agent = await initialize_command_line_agent()
    logger.info("CommandLineAgent initialized.")

    logger.info("Initializing ChromeAgent...")
    chrome_agent, chrome_toolkit = await initialize_chrome_agent()
    logger.info("ChromeAgent initialized.")
    
    # Initialize Orchestrator with sub-agents as tools
    orchestrator = Orchestrator(
        sub_agents=[cli_agent, chrome_agent],
        toolkits=[chrome_toolkit]
    )
    
    logger.info("Orchestrator initialized successfully.")
    
    # Log initialization report
    report = orchestrator.initialization_report()
    logger.debug(f"Orchestrator Configuration: {report}")
    
    return orchestrator
