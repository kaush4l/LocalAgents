from pathlib import Path
import inspect
from typing import Callable, Any, Literal

from pydantic import BaseModel, Field, PrivateAttr

from core.inference import invoke
from core.responses import BaseResponse, ResponseFormat, ReActResponse


class Message(BaseModel):
    """A single message in the conversation history."""
    role: Literal["system", "user", "assistant"]
    content: str


class MultiModal(BaseModel):
    """Placeholder for multimodal input configuration."""
    model_config = {"arbitrary_types_allowed": True}
    
    modality: Literal["image", "audio", "video"]
    input_function: Callable = None
    input_object: Any = None

    def collect_input(self):
        """Collect input data by calling the input function and storing the result."""
        if self.input_function is None:
            return
        try:
            self.input_object = self.input_function()
        except Exception:
            pass


class BaseContext(BaseModel):
    """Base context engine for LLM interactions.
    
    Provides:
    - System prompt loading from file
    - Tool instructions generation
    - Response model instructions generation
    - Message history management
    - Prompt rendering using t-strings
    - Sync-first LLM invocation with response parsing
    """
    model_config = {"arbitrary_types_allowed": True}
    
    name: str = Field(default="DefaultEngine")
    description: str = Field(default="A versatile AI engine configuration.")
    system_instructions: str = Field(default="default")
    model_id: str = Field(default="lms/gpt-oss-120b")
    tools: list = Field(default_factory=list)
    multimodal_inputs: list = Field(default_factory=list)
    history: list = Field(default_factory=list)
    response_model: type = Field(default=BaseResponse)
    response_format: ResponseFormat = Field(default="toon")
    parsed_history: list = Field(default_factory=list)
    
    # Cached context components (private, computed once on init)
    _system_prompt: str = PrivateAttr(default="")
    _tool_instructions: str = PrivateAttr(default="")
    _response_instructions: str = PrivateAttr(default="")
    _static_context: str = PrivateAttr(default="")
    
    def __init__(self, **data):
        """Initialize the context and convert all parameters into cached instructions."""
        super().__init__(**data)
        self._system_prompt = self._convert_system_instructions(self.system_instructions)
        self._tool_instructions = self._convert_tools_to_instructions(self.tools)
        self._response_instructions = self._convert_response_model_to_instructions(self.response_model, self.response_format)
        self._static_context = self._build_static_context()
    
    def _convert_system_instructions(self, system_instructions):
        """Convert system instructions input to prompt text.
        
        If it's a file reference (e.g., 'default'), load from prompts/{name}.md.
        Otherwise use the string as-is.
        """
        prompt_path = Path("prompts") / f"{system_instructions}.md"
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8").strip()
        return system_instructions
    
    def _convert_tools_to_instructions(self, tools):
        """Convert a list of tools (callables or dicts) into text instructions for the LLM."""
        if not tools:
            return ""
        
        lines = ["## AVAILABLE TOOLS", ""]
        for tool in tools:
            if callable(tool):
                name = tool.__name__
                doc = (tool.__doc__ or "No description").strip().split("\n")[0]
                try:
                    sig = inspect.signature(tool)
                    params = ", ".join(
                        f"{p.name}: {p.annotation.__name__ if p.annotation != inspect.Parameter.empty else 'Any'}"
                        for p in sig.parameters.values()
                    )
                except (ValueError, TypeError):
                    params = "..."
                lines.append(f"- {name}({params}) - {doc}")
            elif isinstance(tool, dict):
                name = tool.get("name", "unnamed_tool")
                desc = tool.get("description", "No description")
                params = tool.get("parameters", "...")
                lines.append(f"- {name}({params}) - {desc}")
            else:
                lines.append(f"- {tool}")
        
        return "\n".join(lines)
    
    def _convert_response_model_to_instructions(self, response_model, response_format):
        """Convert response model class to instruction text."""
        return response_model.get_instructions(response_format)
    
    def _build_static_context(self):
        """Build the static portion of the prompt (system + tools + response protocol).
        
        Returns the combined static context string.
        """
        sections = [self._system_prompt]
        
        if self._tool_instructions:
            sections.append(self._tool_instructions)
        
        sections.append("## RESPONSE PROTOCOL (STRICT)")
        sections.append(self._response_instructions)
        
        return "\n\n".join(sections)
    
    def format_history(self, limit=20):
        """Format recent message history for inclusion in prompt."""
        if not self.history:
            return ""
        
        recent = self.history[-limit:]
        lines = ["## CONVERSATION HISTORY", ""]
        for i, msg in enumerate(recent, 1):
            if isinstance(msg, Message):
                lines.append(f"{i}. [{msg.role.upper()}]: {msg.content}")
            else:
                lines.append(f"{i}. {msg}")
        
        return "\n".join(lines)
    
    def render(self, user_input):
        """Render the full prompt by combining cached static context with dynamic history.
        
        Only the history is re-computed each round.
        """
        history = self.format_history()
        
        # Combine static context with dynamic parts
        if history:
            return f"{self._static_context}\n\n{history}\n\nUser: {user_input}\nAssistant:"
        else:
            return f"{self._static_context}\n\nUser: {user_input}\nAssistant:"
    
    def invoke(self, query):
        """Invoke the LLM with the given query and return a parsed response.
        
        Sync-first implementation for free-threaded Python 3.14.
        """
        # Add user message to history
        self.history.append(Message(role="user", content=query))
        
        # Render full prompt
        prompt = self.render(query)
        
        # Call LLM (sync)
        raw_response = invoke(self.model_id, prompt)
        
        if raw_response is None:
            raw_response = ""
        
        # Add assistant response to history
        self.history.append(Message(role="assistant", content=raw_response))
        
        # Parse response using response model
        try:
            parsed = self.response_model.from_raw(raw_response, self.response_format)
            self.parsed_history.append(parsed.answer)
            return parsed
        except Exception as e:
            # Return raw on parse failure, store None in parsed history
            self.parsed_history.append(None)
            # Create a minimal response with error info
            raise ValueError(f"Failed to parse response: {e}\nRaw: {raw_response}")


class ReActContext(BaseContext):
    """ReAct-style context that loops until an answer action is received.
    
    Extends BaseContext with iterative tool-calling loop.
    """
    def __init__(self, **data):
        """Initialize with ReActResponse as default, then call parent init."""
        if "response_model" not in data or data["response_model"] == BaseResponse:
            data["response_model"] = ReActResponse
        super().__init__(**data)
    
    def invoke(self, query):
        """Invoke with ReAct loop until answer or max iterations."""
        # Add user message to history
        self.history.append(Message(role="user", content=query))
        
        while True:
            prompt = self.render(query)
            raw_response = invoke(self.model_id, prompt)
            
            if raw_response is None:
                raw_response = ""
            
            self.history.append(Message(role="assistant", content=raw_response))

            parsed = self.response_model.from_raw(raw_response, self.response_format)
            self.parsed_history.append(parsed)

            # Check if we have a final answer
            if hasattr(parsed, "action") and parsed.action == "answer":
                return parsed

            # If tool action, we would execute tool here and continue
            # For now, just continue to next iteration
            if hasattr(parsed, "action") and parsed.action == "tool":
                # Placeholder for tool execution
                tool_result = f"[Tool execution not implemented: {parsed.answer}]"
                self.history.append(Message(role="user", content=f"Tool result: {tool_result}"))
                continue

            # No recognized action, return as-is
            return parsed
