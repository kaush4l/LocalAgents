"""
Inference module for LLM invocation.
Supports multiple backends: LM Studio, OpenAI, and local testing.
"""
import os
import asyncio
import logging
from typing import Any, Dict, Optional
from openai import OpenAI
from .config import settings

logger = logging.getLogger(__name__)


async def invoke(
    prompt: str, 
    model_id: Optional[str] = None,
    response_model: Optional[type] = None,
    response_format: str = "json"
) -> Any:
    """Invoke an LLM with the given prompt.
    
    Assumes an OpenAI-compatible API backend.
    
    Args:
        prompt: The full prompt to send to the model
        model_id: Model identifier (e.g., "gpt-4o")
        response_model: Optional Pydantic model for structured parsing
        response_format: Format to use for structured instructions (json/toon)
    
    Returns:
        The model's response (structured object if response_model provided, else string)
    """
    model_id = model_id or settings.MODEL_ID
    
    # Simple model_id handling
    if "/" in model_id:
        _, model = model_id.split("/", 1)
    else:
        model = model_id
    
    logger.debug(f"Invoking {model} with prompt of {len(prompt)} chars")
    
    try:
        return await _invoke_llm(prompt, model, response_model)
    except Exception as e:
        logger.error(f"Inference failed for {model}: {e}")
        raise


async def _invoke_llm(prompt: str, model: str, response_model: Optional[type] = None) -> Any:
    """Invoke OpenAI-compatible API with support for structured outputs."""
    loop = asyncio.get_running_loop()
    
    def _call():
        # Use LMS if specified, otherwise default client
        if settings.LMS_PROVIDER_URL and "lms" in settings.MODEL_ID:
            client = OpenAI(
                base_url=settings.LMS_PROVIDER_URL,
                api_key="lm-studio"
            )
        else:
            client = OpenAI()
            
        if response_model:
            # Use the latest structured response API
            response = client.beta.chat.completions.parse(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                response_format=response_model,
                max_tokens=settings.MAX_TOKENS,
                temperature=0.7,
            )
            return response.choices[0].message.parsed
        else:
            # Regular completion
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=settings.MAX_TOKENS,
                temperature=0.7,
            )
            return response.choices[0].message.content or ""
    
    return await loop.run_in_executor(None, _call)
