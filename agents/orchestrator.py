"""
Orchestrator Agent - The main coordinator that delegates tasks to specialized agents.

Pre-loads all sub-agents and creates a single orchestrator instance.
Sub-agents are imported as ready-to-use instances (no initialization needed).
"""
import logging
from core.engine import ReActContext
from core.responses import ReActResponse
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

