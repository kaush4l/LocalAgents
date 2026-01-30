"""
Inference module for LLM invocation.
Supports multiple backends: LM Studio, OpenAI, and local testing.
"""
import asyncio
import logging
from typing import Any, Optional
from openai import OpenAI
from . import config
from .retry import retry_async, INFERENCE_RETRY
from .responses import BaseResponse

logger = logging.getLogger(__name__)


async def invoke(
    prompt: str, 
    model_id: Optional[str] = None,
    response_model: Optional[type] = None,
) -> Any:
    """Invoke an LLM with the given prompt.
    
    Assumes an OpenAI-compatible API backend.
    
    Args:
        prompt: The full prompt to send to the model
        model_id: Model identifier (e.g., "gpt-4o")
        response_model: Optional Pydantic model for structured parsing
    
    Returns:
        The model's response (structured object if response_model provided, else string)
    """
    model_id = model_id or config.MODEL_ID
    
    # Simple model_id handling
    if "/" in model_id:
        _, model = model_id.split("/", 1)
    else:
        model = model_id
    
    logger.debug(f"Invoking {model} with prompt of {len(prompt)} chars")
    
    async def _call():
        return await _invoke_llm(prompt, model, response_model)
    
    return await retry_async(_call, INFERENCE_RETRY)


async def _invoke_llm(prompt: str, model: str, response_model: Optional[type] = None) -> Any:
    """Invoke OpenAI-compatible API with support for structured outputs."""
    loop = asyncio.get_running_loop()
    
    def _call():
        # Use LMS if specified, otherwise default client
        if config.LMS_PROVIDER_URL and "lms" in config.MODEL_ID:
            client = OpenAI(
                base_url=config.LMS_PROVIDER_URL,
                api_key="lm-studio"
            )
        else:
            client = OpenAI()
            
        # Always request plain text from the backend and parse locally.
        # This avoids backend-dependent structured parsing and removes the
        # low-value try/except fallback layer.
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=config.MAX_TOKENS,
            temperature=0.7,
        )
        text = response.choices[0].message.content or ""

        if response_model and isinstance(response_model, type) and issubclass(response_model, BaseResponse):
            return response_model.from_raw(text)
        return text
    
    return await loop.run_in_executor(None, _call)
