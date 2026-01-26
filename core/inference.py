"""
Inference module for LLM invocation.
Supports multiple backends: LM Studio, OpenAI, and local testing.
"""
import os
import asyncio
import logging
from typing import Any, Dict, Optional

from .config import settings

logger = logging.getLogger(__name__)

# Check for OpenAI availability
try:
    from openai import OpenAI
    _HAVE_OPENAI = True
except ImportError:
    _HAVE_OPENAI = False
    logger.warning("OpenAI package not available. Using fallback inference.")


async def invoke(prompt: str, model_id: Optional[str] = None) -> Dict[str, Any] | str:
    """Invoke an LLM with the given prompt.
    
    Supports multiple providers:
    - lms/*: LM Studio (local models)
    - openai/*: OpenAI API
    - Fallback: Test mode with deterministic responses
    
    Args:
        prompt: The full prompt to send to the model
        model_id: Provider/model identifier (e.g., "lms/qwen3-8b")
    
    Returns:
        The model's response (string or dict)
    """
    model_id = model_id or settings.MODEL_ID
    
    # Parse provider from model_id
    if "/" in model_id:
        provider, model = model_id.split("/", 1)
    else:
        provider = "lms"
        model = model_id
    
    logger.debug(f"Invoking {provider}/{model} with prompt of {len(prompt)} chars")
    
    # LM Studio (local OpenAI-compatible API)
    if provider == "lms" and _HAVE_OPENAI:
        try:
            result = await _invoke_lmstudio(prompt, model)
            return result
        except Exception as e:
            logger.warning(f"LM Studio invocation failed: {e}. Falling back to test mode.")
    
    # OpenAI API
    if provider == "openai" and _HAVE_OPENAI and os.getenv("OPENAI_API_KEY"):
        try:
            result = await _invoke_openai(prompt, model)
            return result
        except Exception as e:
            logger.warning(f"OpenAI invocation failed: {e}. Falling back to test mode.")
    
    # Fallback: Test/deterministic mode
    return _test_response(prompt)


async def _invoke_lmstudio(prompt: str, model: str) -> str:
    """Invoke LM Studio's OpenAI-compatible API."""
    loop = asyncio.get_running_loop()
    
    def _call():
        client = OpenAI(
            base_url=settings.LMS_PROVIDER_URL,
            api_key="lm-studio"  # LM Studio doesn't validate API keys
        )
        
        # Try chat completion format first (more common)
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2048,
                temperature=0.7,
            )
            return response.choices[0].message.content or ""
        except Exception:
            # Fallback to completion API
            response = client.completions.create(
                model=model,
                prompt=prompt,
                max_tokens=2048,
                temperature=0.7,
            )
            return response.choices[0].text or ""
    
    result = await loop.run_in_executor(None, _call)
    return result


async def _invoke_openai(prompt: str, model: str) -> str:
    """Invoke OpenAI's API."""
    loop = asyncio.get_running_loop()
    
    def _call():
        client = OpenAI()
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2048,
            temperature=0.7,
        )
        return response.choices[0].message.content or ""
    
    result = await loop.run_in_executor(None, _call)
    return result


def _test_response(prompt: str) -> Dict[str, Any]:
    """Generate a test response for development without an LLM backend.
    
    Provides deterministic responses for testing the workflow.
    """
    lower_prompt = prompt.lower()
    
    # Detect if this looks like a tool-calling scenario
    if "execute_command" in lower_prompt or "run" in lower_prompt and "command" in lower_prompt:
        # Check if there's an observation in the prompt (meaning tool was already called)
        if "observation:" in lower_prompt:
            return {
                "rephrase": "I have received the command output.",
                "reverse": "The command has been executed successfully. I should report the results.",
                "action": "answer",
                "answer": "The command has been executed. Please see the output above."
            }
        else:
            return {
                "rephrase": "You want me to execute a command.",
                "reverse": "I'll use the execute_command tool to run this.",
                "action": "tool",
                "answer": 'execute_command({"command": "echo Hello from test mode!"})'
            }
    
    # Check for CommandLineAgent delegation
    if "commandlineagent" in lower_prompt:
        if "observation:" in lower_prompt:
            return {
                "rephrase": "The CommandLineAgent has completed its task.",
                "reverse": "I should synthesize and report the results.",
                "action": "answer",
                "answer": "Very good, sir. The operation has been completed successfully. The CommandLineAgent has executed the requested task."
            }
        else:
            return {
                "rephrase": "You need assistance with a system task.",
                "reverse": "I shall delegate this to the CommandLineAgent.",
                "action": "tool",
                "answer": 'CommandLineAgent({"query": "Please execute the requested task."})'
            }
    
    # Default conversational response
    return {
        "rephrase": "You have a general question or request.",
        "reverse": "I can answer this directly without using any tools.",
        "action": "answer",
        "answer": f"Hello! I'm running in test mode. Your message was received and processed. In production, I would provide a full AI-powered response. (Prompt length: {len(prompt)} chars)"
    }


async def check_lmstudio_health() -> Dict[str, Any]:
    """Check if LM Studio is available and responding."""
    if not _HAVE_OPENAI:
        return {"available": False, "error": "OpenAI package not installed"}
    
    try:
        loop = asyncio.get_running_loop()
        
        def _check():
            client = OpenAI(
                base_url=settings.LMS_PROVIDER_URL,
                api_key="lm-studio"
            )
            models = client.models.list()
            return {
                "available": True,
                "models": [m.id for m in models.data],
                "base_url": settings.LMS_PROVIDER_URL
            }
        
        result = await loop.run_in_executor(None, _check)
        return result
    except Exception as e:
        return {"available": False, "error": str(e)}
