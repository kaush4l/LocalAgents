"""
Orchestrator Agent - The main coordinator that delegates tasks to specialized agents.

Pre-loads all sub-agents and creates a single orchestrator instance.
Sub-agents are imported as ready-to-use instances (no initialization needed).
"""
import logging
from core.engine import ReActContext
from core.responses import ReActResponse
from core import config

logger = logging.getLogger(__name__)

# Orchestrator is initialized via an async function to handle sub-agent initialization
orchestrator = None

async def close_orchestrator():
    """Cleanup function for the orchestrator and its resources."""
    global orchestrator
    if orchestrator:
        await orchestrator.close()

async def initialize_orchestrator():
    """
    Initialize the Orchestrator agent using pre-initialized sub-agents.
    
    Returns:
        orchestrator: The main orchestrator context
    """
    global orchestrator
    
    if orchestrator:
        return orchestrator

    logger.info("Initializing Orchestrator...")
    
    # Import pre-initialized agents
    from .command_line_agent import command_line_agent
    from .chrome_agent import chrome_agent
    
    # Initialize Orchestrator as a direct ReActContext instance
    orchestrator = ReActContext(
        name="orchestrator",
        description="The main assistant that coordinates and delegates tasks to specialized agents.",
        system_instructions="orchestrator",
        model_id=config.MODEL_ID,
        tools=[command_line_agent, chrome_agent],
        response_model=ReActResponse,
        response_format="toon",
        max_iterations=config.MAX_ITERATIONS,
    )
    
    logger.info("Orchestrator initialized successfully.")
    
    return orchestrator
from core.config import settings
from .command_line_agent import command_line_agent
from .chrome_agent import chrome_agent

logger = logging.getLogger(__name__)

# Create the Orchestrator instance with sub-agents as tools
# All sub-agents are pre-initialized when imported above
orchestrator = ReActContext(
    name="orchestrator",
    description="The main assistant that coordinates and delegates tasks to specialized agents.",
    system_instructions="orchestrator",
    model_id=settings.MODEL_ID,
    tools=[command_line_agent, chrome_agent],
    response_model=ReActResponse,
    response_format="json",
    max_iterations=settings.MAX_ITERATIONS,
)

logger.info("Orchestrator instance created with pre-loaded sub-agents")

>>>>>>> wip/save-local-20260129-235217
