"""
Core context engine for LLM interactions with ReAct-style tool calling.
Provides the foundation for multi-agent workflows with streaming events.
"""
import json
import asyncio
import inspect
import re
import logging
from pathlib import Path
from typing import Any, Callable, Literal
from datetime import datetime

from pydantic import BaseModel, Field, PrivateAttr

from .config import settings
from .responses import BaseResponse, ReActResponse, ChatMessage

logger = logging.getLogger(__name__)


class Message(BaseModel):
    """A single message in the conversation history."""
    role: Literal["system", "user", "assistant"]
    content: str


class BaseContext(BaseModel):
    """Base context engine for LLM interactions.
    
    Provides:
    - System prompt loading from file (prompts/*.md)
    - Tool instructions generation (callables, dicts, sub-agents)
    - Response model instructions generation
    - Message history management
    - LLM invocation with structured response parsing
    - Real-time event streaming via callbacks
    """
    model_config = {"arbitrary_types_allowed": True}
    
    name: str = Field(default="Agent")
    description: str = Field(default="A versatile AI agent.")
    system_instructions: str = Field(default="default")
    model_id: str = Field(default_factory=lambda: settings.MODEL_ID)
    tools: list = Field(default_factory=list)
    history: list = Field(default_factory=list)
    response_model: type = Field(default=ReActResponse)
    response_format: str = Field(default="json")
    max_iterations: int = Field(default_factory=lambda: settings.MAX_ITERATIONS)
    
    # Event callback for real-time streaming
    event_callback: Any = Field(default=None, exclude=True)
    
    # Cached context components (private)
    _system_prompt: str = PrivateAttr(default="")
    _tool_instructions: str = PrivateAttr(default="")
    _response_instructions: str = PrivateAttr(default="")
    _static_context: str = PrivateAttr(default="")
    _prompt_root: Path = PrivateAttr(default=Path.cwd() / "prompts")
    
    def __init__(self, **data):
        """Initialize the context and convert all parameters into cached instructions."""
        super().__init__(**data)
        self._prompt_root = Path.cwd() / "prompts"
        self._system_prompt = self._convert_system_instructions(self.system_instructions)
        self._tool_instructions = self._convert_tools_to_instructions(self.tools)
        self._response_instructions = self._convert_response_model_to_instructions(
            self.response_model, self.response_format
        )
        self._static_context = self._build_static_context()
    
    def set_event_callback(self, callback: Callable):
        """Set callback to receive real-time events."""
        self.event_callback = callback
    
    async def _emit_event(self, event_type: str, data: dict):
        """Emit an event to the registered callback."""
        if self.event_callback:
            event = {
                "type": event_type,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "data": data
            }
            if asyncio.iscoroutinefunction(self.event_callback):
                await self.event_callback(event)
            else:
                self.event_callback(event)
    
    def _convert_system_instructions(self, system_instructions: str) -> str:
        """Convert system instructions input to prompt text."""
        if not system_instructions:
            return ""
        
        # Accept explicit file paths
        direct_path = Path(system_instructions)
        if direct_path.suffix == ".md" and direct_path.exists():
            return direct_path.read_text(encoding="utf-8").strip()
        
        # Fallback to prompts/{name}.md
        prompt_path = self._prompt_root / f"{system_instructions}.md"
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8").strip()
        
        return str(system_instructions)
    
    def _convert_tools_to_instructions(self, tools: list) -> str:
        """Convert a list of tools into text instructions."""
        if not tools:
            return ""
        
        lines = [
            "## AVAILABLE TOOLS",
            "To call a tool, use JSON format: tool_name({\"arg1\": \"value\"})",
            ""
        ]
        
        for tool in tools:
            if callable(tool):
                name = tool.__name__
                doc = (tool.__doc__ or "No description").strip().split("\n")[0]
                sig = inspect.signature(tool)
                params = ", ".join(
                    f"{p.name}: {p.annotation.__name__ if p.annotation != inspect.Parameter.empty else 'Any'}"
                    for p in sig.parameters.values()
                )
                lines.append(f"- {name}({params}) - {doc}")
            elif isinstance(tool, dict):
                name = tool.get("name", "unnamed_tool")
                desc = tool.get("description", "No description")
                params = tool.get("parameters", "...")
                lines.append(f"- {name}({params}) - {desc}")
            elif isinstance(tool, BaseContext):
                lines.append(f"- {tool.name}(query: str) - {tool.description}")
            else:
                lines.append(f"- {tool}")
        
        return "\n".join(lines) if len(lines) > 3 else ""
    
    def _convert_response_model_to_instructions(self, response_model, response_format: str) -> str:
        """Convert response model class to instruction text."""
        return response_model.get_instructions(response_format)
    
    def _build_static_context(self) -> str:
        """Build the static portion of the prompt."""
        parts = [self._system_prompt]
        
        if self._tool_instructions:
            parts.append(self._tool_instructions)
        
        parts.append("## RESPONSE PROTOCOL (STRICT)")
        parts.append(self._response_instructions)
        
        return "\n\n".join(parts)
    
    def format_history(self, limit: int = 20, exclude_user_input: str | None = None) -> str:
        """Format recent message history for inclusion in prompt."""
        if not self.history:
            return ""
        
        recent = self.history[-limit:]
        if exclude_user_input is not None:
            recent = [
                msg for msg in recent
                if not (isinstance(msg, Message) and msg.role == "user" and msg.content == exclude_user_input)
            ]
        
        if not recent:
            return ""
        
        lines = ["## CONVERSATION HISTORY", ""]
        for i, msg in enumerate(recent, 1):
            if isinstance(msg, Message):
                lines.append(f"{i}. [{msg.role.upper()}]: {msg.content}")
            else:
                lines.append(f"{i}. {msg}")
        
        return "\n".join(lines)
    
    def render(self, user_input: str) -> str:
        """Render the full prompt by combining cached static context with dynamic history."""
        user_text = "" if user_input is None else str(user_input)
        history = self.format_history(exclude_user_input=user_text)
        
        history_block = f"\n\n{history}" if history else ""
        user_block = f"\n\n## USER INPUT\n{user_text}"
        
        return f"{self._static_context}{history_block}{user_block}\n\nAssistant:"
    
    async def invoke(self, query: str):
        """Invoke the LLM with the given query and return a parsed response."""
        from . import inference
        
        self.history.append(Message(role="user", content=query))
        
        prompt = self.render(query)
        raw_response = await inference.invoke(prompt, model_id=self.model_id)
        
        if raw_response is None:
            raw_response = ""
        
        raw_str = raw_response if isinstance(raw_response, str) else json.dumps(raw_response)
        self.history.append(Message(role="assistant", content=raw_str))
        
        parsed = self._safe_parse_response(raw_response)
        return parsed
    
    def _safe_parse_response(self, raw_response):
        """Parse response, returning a safe fallback on errors."""
        try:
            return self.response_model.from_raw(raw_response, self.response_format)
        except Exception as e:
            return self._fallback_response(raw_response, e)
    
    def _fallback_response(self, raw_response, error: Exception):
        """Create a minimal response object that preserves the failure context."""
        error_msg = f"System Error: {type(error).__name__} - {str(error)}"
        
        if issubclass(self.response_model, ReActResponse):
            return self.response_model(
                rephrase="The system encountered an internal processing error.",
                reverse="Analyze the error message and retry with a different approach.",
                action="answer",
                answer=f"An error occurred: {error_msg}. Please try again."
            )
        
        try:
            return self.response_model.model_construct()
        except Exception:
            return BaseResponse.model_construct()
    
    def initialization_report(self) -> dict:
        """Return a compact snapshot of the context configuration for verification."""
        tool_names = []
        for tool in self.tools:
            if callable(tool):
                tool_names.append(tool.__name__)
            elif isinstance(tool, dict):
                tool_names.append(tool.get("name", "unnamed_tool"))
            elif isinstance(tool, BaseContext):
                tool_names.append(tool.name)
            else:
                tool_names.append(str(tool))
        
        return {
            "name": self.name,
            "description": self.description,
            "model_id": self.model_id,
            "system_instructions": self.system_instructions,
            "response_format": self.response_format,
            "tool_count": len(self.tools),
            "tool_names": tool_names,
            "history_count": len(self.history),
            "has_system_prompt": bool(self._system_prompt),
            "has_tool_instructions": bool(self._tool_instructions),
        }


class ReActContext(BaseContext):
    """ReAct-style context that loops until an answer action is received.
    
    Extends BaseContext with iterative tool-calling loop:
    1. LLM generates a response with action='tool' or action='answer'
    2. If action='tool', execute the tool and feed observation back
    3. Repeat until action='answer' or max_iterations reached
    """
    
    def __init__(self, **data):
        """Initialize with ReActResponse as default."""
        if "response_model" not in data or data["response_model"] == BaseResponse:
            data["response_model"] = ReActResponse
        super().__init__(**data)
    
    async def chat(self, user_input: str, history: list = None) -> str:
        """Adapter for FastAPI/WebSocket chat interface."""
        if history:
            new_history = []
            for h in history:
                new_history.append(Message(role=h.get("role", "user"), content=h.get("content", "")))
            self.history = new_history
        
        result = await self.invoke(user_input)
        return getattr(result, "answer", str(result))
    
    async def invoke(self, query: str):
        """Invoke with ReAct loop until an answer or max iterations reached."""
        from . import inference
        
        self.history.append(Message(role="user", content=query))
        last_parsed = None
        tool_call_history = {}
        
        await self._emit_event("status", {
            "agent": self.name,
            "state": "thinking",
            "message": f"{self.name} is processing..."
        })
        
        for iteration in range(max(1, self.max_iterations)):
            prompt = self.render(query)
            raw_response = await inference.invoke(prompt, model_id=self.model_id)
            
            if raw_response is None:
                raw_response = ""
            
            raw_str = raw_response if isinstance(raw_response, str) else json.dumps(raw_response)
            logger.debug(f"LLM response iter={iteration} chars={len(raw_str)}")
            
            try:
                parsed = self.response_model.from_raw(raw_response, self.response_format)
                last_parsed = parsed
                
                # Emit thought event
                await self._emit_event("thought", {
                    "content": getattr(parsed, "reverse", "") or getattr(parsed, "rephrase", ""),
                    "agent": self.name,
                    "metadata": {"iteration": iteration, "action": getattr(parsed, "action", "")}
                })
                
                # Store condensed history
                action = getattr(parsed, "action", None)
                answer = getattr(parsed, "answer", "")
                answer_short = answer[:80] + "..." if len(answer) > 80 else answer
                condensed = f"[action={action}] {answer_short}"
                self.history.append(Message(role="assistant", content=condensed))
            
            except Exception as e:
                observation = f"Format Error: Failed to parse your response. Error: {e}. Follow the RESPONSE PROTOCOL strictly."
                self.history.append(Message(role="user", content=f"Observation: {observation}"))
                last_parsed = self._fallback_response(raw_str, e)
                logger.warning(f"Parse error iter={iteration} error={type(e).__name__}")
                continue
            
            action = getattr(parsed, "action", None)
            
            if action == "answer":
                logger.info("Agent completed with answer action")
                return parsed
            
            if action == "tool":
                tool_calls_str = getattr(parsed, "answer", "")
                
                # Loop Detection
                tool_call_history[tool_calls_str] = tool_call_history.get(tool_calls_str, 0) + 1
                if tool_call_history[tool_calls_str] > 2:
                    observation = f"Error: You have attempted the same tool call {tool_call_history[tool_calls_str]} times. Change your strategy or parameters."
                    logger.warning(f"Loop detected for tool call: {tool_calls_str}")
                else:
                    observation = await self.execute_tool_calls(tool_calls_str)
                
                observation_short = observation[:100] + "..." if len(observation) > 100 else observation
                logger.info(f"Tool executed: {observation_short}")
                self.history.append(Message(role="user", content=f"Observation: {observation}"))
                continue
            
            break
        
        if last_parsed is None:
            logger.error("Max iterations reached without valid response")
            return self._fallback_response("", RuntimeError("No successful parse"))
        return last_parsed
    
    def _parse_tool_call(self, call_str: str) -> tuple:
        """Parse a single tool call string into (name, args) tuple."""
        call_str = call_str.strip()
        
        # Pattern: tool_name({...}) or tool_name(...)
        match = re.match(r'(\w+)\s*\((.*)\)\s*$', call_str, re.DOTALL)
        if not match:
            return None, {}
        
        name = match.group(1)
        args_str = match.group(2).strip()
        
        if not args_str:
            return name, {}
        
        try:
            args = json.loads(args_str)
            return name, args if isinstance(args, dict) else {}
        except json.JSONDecodeError:
            # Try to parse key=value format
            args = {}
            for part in args_str.split(","):
                if "=" in part:
                    k, v = part.split("=", 1)
                    args[k.strip()] = v.strip().strip('"\'')
            return name, args
    
    def _parse_tool_calls(self, answer_str: str) -> list:
        """Parse multiple tool calls from a string separated by newlines."""
        calls = []
        for line in answer_str.splitlines():
            line = line.strip()
            if not line:
                continue
            
            name, args = self._parse_tool_call(line)
            if name:
                calls.append((name, args))
        
        # If no calls found, try parsing the whole thing as one call
        if not calls:
            name, args = self._parse_tool_call(answer_str)
            if name:
                calls.append((name, args))
        
        return calls
    
    async def _execute_tool(self, tool_name: str, tool_args: dict):
        """Execute a tool by name."""
        tool_func = None
        for t in self.tools:
            if callable(t) and t.__name__ == tool_name:
                tool_func = t
                break
            elif isinstance(t, dict) and t.get("name") == tool_name:
                tool_func = t.get("callable")
                break
            elif isinstance(t, BaseContext) and t.name == tool_name:
                tool_func = t
                break
        
        if not tool_func:
            return f"Error: Tool {tool_name} not found."
        
        # Emit: tool_call_start
        await self._emit_event("tool_call_start", {
            "tool_name": tool_name,
            "args": tool_args,
            "agent": self.name
        })
        
        await self._emit_event("status", {
            "agent": self.name,
            "state": f"tool:{tool_name}",
            "message": f"Executing {tool_name}..."
        })
        
        try:
            logger.info(f"Executing tool: {tool_name} with {tool_args}")
            
            result = None
            
            # Handle Sub-Agents (BaseContext instances)
            if isinstance(tool_func, BaseContext):
                sub_query = tool_args.get("query")
                if not sub_query:
                    vals = list(tool_args.values())
                    if vals:
                        sub_query = vals[0]
                
                if not sub_query:
                    result = "Error: Sub-agent tool requires a 'query' argument."
                else:
                    res_obj = await tool_func.invoke(str(sub_query))
                    if hasattr(res_obj, "action") and res_obj.action == "tool":
                        result = f"Error: {tool_func.name} stopped prematurely while trying to execute: {res_obj.answer}. Task incomplete."
                    elif hasattr(res_obj, "answer"):
                        result = res_obj.answer
                    else:
                        result = str(res_obj)
            
            # Handle Direct Callables
            elif callable(tool_func):
                if asyncio.iscoroutinefunction(tool_func):
                    result = await tool_func(**tool_args)
                else:
                    result = tool_func(**tool_args)
            else:
                result = f"Error: Tool {tool_name} is not executable"
            
            # Emit: tool_call_end
            await self._emit_event("tool_call_end", {
                "tool_name": tool_name,
                "success": True,
                "agent": self.name
            })
            
            await self._emit_event("status", {
                "agent": self.name,
                "state": "thinking",
                "message": f"{self.name} analyzing tool result..."
            })
            
            await self._emit_event("log", {
                "level": "info",
                "content": f"Tool {tool_name} returned: {str(result)[:180]}",
                "agent": self.name
            })
            
            return result
        
        except Exception as e:
            err = f"Error executing tool {tool_name}: {e}"
            await self._emit_event("tool_call_end", {
                "tool_name": tool_name,
                "success": False,
                "agent": self.name
            })
            await self._emit_event("log", {
                "level": "error",
                "content": err,
                "agent": self.name
            })
            return err
    
    async def execute_tool_calls(self, tool_calls_str: str) -> str:
        """Execute tool calls described in a tool-call string and return an observation string."""
        raw = (tool_calls_str or "").strip()
        tool_calls = self._parse_tool_calls(raw)
        
        if not tool_calls:
            return f"Error: Could not parse tool call from: {raw[:100]}"
        
        results = []
        for name, args in tool_calls:
            result = await self._execute_tool(name, args)
            results.append(f"{name}: {result}")
        
        return "\n".join(results)
