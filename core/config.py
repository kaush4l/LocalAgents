"""
Global configuration for the AppleShortcuts agent system.
"""
import os
from typing import Literal

# LLM Configuration
DEFAULT_MODEL_ID = os.getenv("MODEL_ID", "lms/openai/gpt-oss-20b")
DEFAULT_RESPONSE_FORMAT: Literal["json", "toon"] = "json"
DEFAULT_MAX_ITERATIONS = 10

# Provider Configuration
LMS_PROVIDER_URL = os.getenv("LMS_PROVIDER_URL", "http://127.0.0.1:1234/v1")

# MCP Configuration
MCP_ENABLED = os.getenv("MCP_ENABLED", "true").lower() == "true"

# Logging Configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Agent Configuration
AGENT_TIMEOUT_SECONDS = int(os.getenv("AGENT_TIMEOUT", "300"))

# Response Protocol
RESPONSE_FORMAT_PRIORITY = ["json", "toon"]  # Order of format preference
