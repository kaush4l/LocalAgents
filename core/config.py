"""
Static configuration for the LocalAgents system.
All values are initialized once at module import time.
"""
import os
from typing import Literal

# =============================================================================
# LLM CONFIGURATION (initialized once at import)
# =============================================================================
MODEL_ID: str = os.getenv("MODEL_ID", "lms/openai/gpt-oss-20b")
RESPONSE_FORMAT: Literal["json", "toon"] = "json"
MAX_TOKENS: int = 32000
MAX_ITERATIONS: int = 8

# =============================================================================
# PROVIDER CONFIGURATION
# =============================================================================
LMS_PROVIDER_URL: str = os.getenv("LMS_PROVIDER_URL", "http://127.0.0.1:1234/v1")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# =============================================================================
# AGENT CONFIGURATION
# =============================================================================
AGENT_TIMEOUT_SECONDS: int = int(os.getenv("AGENT_TIMEOUT", "300"))

# =============================================================================
# SERVER CONFIGURATION
# =============================================================================
HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "8000"))
