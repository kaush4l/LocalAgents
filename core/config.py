"""
Global configuration for the AppleShortcuts agent system.
"""
import os
from typing import Literal

# LLM Configuration
DEFAULT_MODEL_ID = os.getenv("MODEL_ID", "lms/openai/gpt-oss-20b")
DEFAULT_RESPONSE_FORMAT: Literal["json", "toon"] = "json"
DEFAULT_MAX_TOKENS = 32000
DEFAULT_MAX_ITERATIONS = 8

# Provider Configuration
LMS_PROVIDER_URL = os.getenv("LMS_PROVIDER_URL", "http://127.0.0.1:1234/v1")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Logging Configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Agent Configuration
AGENT_TIMEOUT_SECONDS = int(os.getenv("AGENT_TIMEOUT", "300"))

# Server Configuration
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# Response Protocol
RESPONSE_FORMAT_PRIORITY = ["json", "toon"]


class Settings:
    """Settings container for easy access."""
    def __init__(self):
        self.HOST = HOST
        self.PORT = PORT
        self.LMS_PROVIDER_URL = LMS_PROVIDER_URL
        self.MODEL_ID = DEFAULT_MODEL_ID
        self.OPENAI_API_KEY = OPENAI_API_KEY
        self.MAX_ITERATIONS = DEFAULT_MAX_ITERATIONS
        self.MAX_TOKENS = DEFAULT_MAX_TOKENS
        self.RESPONSE_FORMAT = DEFAULT_RESPONSE_FORMAT


settings = Settings()
