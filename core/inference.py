"""Sync-first inference module for free-threaded Python 3.14.

Uses the OpenAI Responses API with synchronous client.
"""


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
    from openai import OpenAI
    
    provider, model = model_id.split("/", 1)
    
    if provider == "lms":
        base_url = "http://127.0.0.1:1234/v1"
        client = OpenAI(base_url=base_url, api_key="lms")
        response = client.responses.create(
            model=model,
            input=prompt
        )
        return response.output_text
    
    if provider == "openai":
        client = OpenAI()
        response = client.responses.create(
            model=model,
            input=prompt
        )
        return response.output_text
    
    return None