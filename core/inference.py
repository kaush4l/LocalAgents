"""Sync-first inference module for free-threaded Python 3.14.

Uses the OpenAI Responses API with synchronous client.
"""
import logging

logger = logging.getLogger(__name__)


def invoke(model_id, prompt, multimodal_data=None):
    """Invoke an LLM with the given prompt.
    
    Sync-first implementation for free-threaded Python 3.14.
    Uses the Responses API for structured output.
    
    Args:
        model_id: Provider/model identifier (e.g., "lms/model-name")
        prompt: The full prompt to send
        multimodal_data: Optional list of multimodal inputs (placeholder)
    
    Returns:
        The model's response text, or None on error
    """
    try:
        from openai import OpenAI
    except ImportError as e:
        logger.error(f"OpenAI client not available: {e}")
        return None

    try:
        provider, model = model_id.split("/", 1)
    except ValueError as e:
        logger.error(f"Invalid model_id format '{model_id}': {e}")
        return None

    try:
        if provider == "lms":
            from core.config import LMS_PROVIDER_URL
            client = OpenAI(base_url=LMS_PROVIDER_URL, api_key="lms")
            response = client.responses.create(
                model=model,
                input=prompt
            )
            return getattr(response, "output_text", "") or ""

        if provider == "openai":
            client = OpenAI()
            response = client.responses.create(
                model=model,
                input=prompt
            )
            return getattr(response, "output_text", "") or ""
        
        logger.warning(f"Unknown provider '{provider}' in model_id '{model_id}'")
        return None
    except Exception as e:
        logger.error(f"LLM invocation failed: {type(e).__name__}: {e}")
        return None

    return None
