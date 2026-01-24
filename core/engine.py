from pathlib import Path
import inspect
import asyncio
from typing import Any, Literal
import re
import json
# from string import templatelib - Removed as not available in 3.13

from pydantic import BaseModel, Field, PrivateAttr

from core.inference import invoke
from core.responses import BaseResponse, ResponseFormat, ReActResponse
from core.logger import get_logger

logger = get_logger("CoreEngine")


class Message(BaseModel):
    """A single message in the conversation history."""
    role: Literal["system", "user", "assistant"]
    content: str


class BaseContext(BaseModel):
    """Base context engine for LLM interactions.
    
    Provides:
    - System prompt loading from file (prompts/*.md)
    - Tool instructions generation (callables, dicts, sub-agents)
    - Response model instructions generation (JSON/TOON formats)
    - Message history management with auto-truncation
    - Prompt rendering using t-strings (Python 3.14+)
    - Sync-first LLM invocation with structured response parsing
    - Parallel tool execution capability via execute_tools_parallel()
    - Safe fallback responses (no exceptions propagated to caller)
    
    Initialization Flow:
    1. Load system prompt from file or use raw string
    2. Generate tool instructions from tools list
    3. Generate response protocol from response_model
    4. Cache static context (immutable portion of prompt)
    
    Usage:
        ctx = BaseContext(
            name="MyAgent",
            system_instructions="my_prompt",  # loads prompts/my_prompt.md
            tools=[my_function],
            response_model=ReActResponse,
            response_format="json"
        )
        result = await ctx.invoke("user query")
    """
    model_config = {"arbitrary_types_allowed": True}
    
    name: str = Field(default="DefaultEngine")
    description: str = Field(default="A versatile AI engine configuration.")
    system_instructions: str = Field(default="default")
    model_id: str = Field(default="lms/openai/gpt-oss-20b")
    tools: list = Field(default_factory=list)
    toolkit: Any = Field(default=None)
    history: list = Field(default_factory=list)
    response_model: type = Field(default=BaseResponse)
    response_format: ResponseFormat = Field(default="toon")
    max_iterations: int = Field(default=8, description="Maximum ReAct loop iterations before aborting.")
    prompt_root: str | Path | None = Field(
        default=None,
        description="Optional override for the prompts/ directory root."
    )
    
    # Cached context components (private, computed once on init)
    _system_prompt: str = PrivateAttr(default="")
    _tool_instructions: str = PrivateAttr(default="")
    _response_instructions: str = PrivateAttr(default="")
    _static_context: str = PrivateAttr(default="")
    _prompt_root: Path = PrivateAttr(default=Path(__file__).resolve().parent.parent / "prompts")
    
    def __init__(self, **data):
        """Initialize the context and convert all parameters into cached instructions."""
        super().__init__(**data)
        self._prompt_root = self._resolve_prompt_root(self.prompt_root)
        self._system_prompt = self._convert_system_instructions(self.system_instructions)
        self._tool_instructions = self._convert_tools_to_instructions(self.tools)
        self._response_instructions = self._convert_response_model_to_instructions(self.response_model, self.response_format)
        self._static_context = self._build_static_context()

    def _resolve_prompt_root(self, prompt_root):
        """Resolve the prompt root directory safely."""
        default_root = Path(__file__).resolve().parent.parent / "prompts"
        if not prompt_root:
            return default_root
        try:
            root_path = Path(prompt_root)
            if not root_path.is_absolute():
                root_path = (default_root.parent / root_path).resolve()
            return root_path
        except Exception:
            return default_root

    def _render_tstring(self, template):
        """Render a string template (legacy support)."""
        return str(template)
    
    def _convert_system_instructions(self, system_instructions):
        """Convert system instructions input to prompt text.
        
        If it's a file reference (e.g., 'default'), load from prompts/{name}.md.
        Otherwise use the string as-is.
        """
        if system_instructions is None:
            return ""

        # Accept explicit file paths (absolute or relative).
        try:
            direct_path = Path(system_instructions)
            if direct_path.suffix == ".md" and direct_path.exists():
                return direct_path.read_text(encoding="utf-8").strip()
        except Exception:
            pass

        # Fallback to prompts/{name}.md under the resolved prompt root.
        prompt_path = self._prompt_root / f"{system_instructions}.md"
        try:
            if prompt_path.exists():
                return prompt_path.read_text(encoding="utf-8").strip()
        except Exception:
            pass

        return str(system_instructions)
    
    def _convert_tools_to_instructions(self, tools):
        """Convert a list of tools (callables, dicts, or Contexts) into text instructions."""
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
                
                # Handle MCP tool schema extraction if present
                mcp_tool = tool.get("mcp_tool")
                if mcp_tool and hasattr(mcp_tool, "input_schema"):
                    schema = mcp_tool.input_schema
                    if hasattr(schema, "model_dump"):
                        schema = schema.model_dump()
                    
                    if isinstance(schema, dict) and "properties" in schema:
                        props = schema["properties"]
                        required = schema.get("required", [])
                        params_list = []
                        for p_name, p_info in props.items():
                            p_type = p_info.get("type", "Any")
                            is_req = "*" if p_name in required else ""
                            params_list.append(f"{p_name}{is_req}: {p_type}")
                        params = ", ".join(params_list)
                    else:
                        params = tool.get("parameters", "...")
                else:
                    params = tool.get("parameters", "...")
                
                lines.append(f"- {name}({params}) - {desc}")
            elif isinstance(tool, BaseContext):
                lines.append(f"- {tool.name}(query: str) - {tool.description}")
            else:
                lines.append(f"- {tool}")
        
        if len(lines) <= 2:  # Only header, no actual tools
            return ""
        
        # Replace the duplicate header with calling instructions
        lines[0] = "## AVAILABLE TOOLS"
        lines[1] = "To call a tool, use JSON format: tool_name({\"arg1\": \"value\"})\nYou can call multiple tools on separate lines."
        
        return "\n".join(lines)
    
    def _convert_response_model_to_instructions(self, response_model, response_format):
        """Convert response model class to instruction text."""
        return response_model.get_instructions(response_format)
    
    def _build_static_context(self) -> str:
        """Build the static portion of the prompt (system + tools + response protocol).
        
        Returns the combined static context string.
        """
        system_prompt = self._system_prompt

        tool_instructions = self._tool_instructions
        has_tool_instructions = bool(tool_instructions)

        response_protocol_header = "## RESPONSE PROTOCOL (STRICT)"
        response_instructions = self._response_instructions

        section_separator = "\n\n"
        empty = ""

        tools_block = (
            f"{tool_instructions}{section_separator}"
            if has_tool_instructions
            else empty
        )

        t_string = f"{system_prompt}{section_separator}{tools_block}{response_protocol_header}{section_separator}{response_instructions}"

        return self._render_tstring(t_string)
    
    def format_history(self, limit=20, exclude_user_input: str | None = None):
        """Format recent message history for inclusion in prompt."""
        if not self.history:
            return ""

        recent = self.history[-limit:]
        if exclude_user_input is not None:
            recent = [
                msg for msg in recent
                if not (isinstance(msg, Message) and msg.role == "user" and msg.content == exclude_user_input)
            ]
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
        user_text = "" if user_input is None else str(user_input)
        history = self.format_history(exclude_user_input=user_text)

        history_block = f"\n\n{history}" if history else ""
        user_block = f"\n\n## USER INPUT\n{user_text}"

        t_string = f"{self._static_context}{history_block}{user_block}\n\nAssistant:"
        return self._render_tstring(t_string)
    
    async def invoke(self, query):
        """Invoke the LLM with the given query and return a parsed response.
        """
        # Add user message to history
        self.history.append(Message(role="user", content=query))
        
        # Render full prompt
        prompt = self.render(query)
        
        # Call LLM (sync - inference is sync in this project)
        raw_response = invoke(self.model_id, prompt)
        
        if raw_response is None:
            raw_response = ""
        
        # Add assistant response to history
        self.history.append(Message(role="assistant", content=raw_response))
        
        # Parse response using response model (never raise; return fallback)
        parsed = self._safe_parse_response(raw_response)
        return parsed

    async def execute_tools_parallel(self, tool_calls, executor):
        """Execute tool calls in parallel using the provided executor coroutine.

        Args:
            tool_calls: list of (tool_name, tool_args)
            executor: coroutine function that accepts (tool_name, tool_args)
        """
        tasks = [executor(name, args) for name, args in tool_calls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [self._normalize_tool_result(r) for r in results]

    def _normalize_tool_result(self, result):
        """Normalize tool execution results into safe, displayable strings."""
        if isinstance(result, Exception):
            return f"Error: {result}"
        return result

    def _safe_parse_response(self, raw_response: str):
        """Parse response, returning a safe fallback on errors (no exceptions raised)."""
        try:
            return self.response_model.from_raw(raw_response, self.response_format)
        except Exception as e:
            return self._fallback_response(raw_response, e)

    def _fallback_response(self, raw_response: str, error: Exception):
        """Create a minimal response object that preserves the failure context."""
        if issubclass(self.response_model, ReActResponse):
            return self.response_model(
                rephrase="Unable to parse model output; returning a safe response.",
                reverse="Validate response format and tool call syntax before retrying.",
                action="answer",
                answer=(
                    "The model response could not be parsed. "
                    "Please retry with strict response formatting."
                )
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
            "response_model": self.response_model.__name__ if hasattr(self.response_model, "__name__") else str(self.response_model),
            "tool_count": len(self.tools),
            "tool_names": tool_names,
            "has_toolkit": bool(self.toolkit),
            "toolkit_last_error": getattr(self.toolkit, "last_error", None),
            "history_count": len(self.history),
            "prompt_root": str(self._prompt_root),
            "prompt_root_exists": self._prompt_root.exists(),
            "has_system_prompt": bool(self._system_prompt),
            "has_tool_instructions": bool(self._tool_instructions),
            "has_response_instructions": bool(self._response_instructions),
            "system_prompt_chars": len(self._system_prompt or ""),
            "tool_instructions_chars": len(self._tool_instructions or ""),
            "response_instructions_chars": len(self._response_instructions or ""),
            "static_context_chars": len(self._static_context or ""),
            "prompt_template": "t-string",
        }


class ReActContext(BaseContext):
    """ReAct-style context that loops until an answer action is received.
    
    Extends BaseContext with iterative tool-calling loop.
    """
    def __init__(self, **data):
        """Initialize with ReActResponse as default, then call parent init."""
        if "response_model" not in data or data["response_model"] == BaseResponse:
            data["response_model"] = ReActResponse
        super().__init__(**data)
    
    async def invoke(self, query):
        """Invoke with ReAct loop until an answer or max iterations reached."""
        self.history.append(Message(role="user", content=query))
        last_parsed = None

        for iteration in range(max(1, self.max_iterations)):
            prompt = self.render(query)
            # inference is sync
            raw_response = invoke(self.model_id, prompt) or ""
            logger.debug(f"LLM response iter={iteration} chars={len(raw_response)}")
            
            try:
                parsed = self.response_model.from_raw(raw_response, self.response_format)
                last_parsed = parsed
                
                # Store condensed history: action + truncated answer only
                action = getattr(parsed, "action", None)
                answer = getattr(parsed, "answer", "")
                answer_short = answer[:80] + "..." if len(answer) > 80 else answer
                condensed = f"[action={action}] {answer_short}"
                self.history.append(Message(role="assistant", content=condensed))
            except Exception as e:
                observation = f"Error parsing response: {e}. Please ensure you follow the response protocol."
                self.history.append(Message(role="user", content=f"Observation: {observation}"))
                last_parsed = self._fallback_response(raw_response, e)
                logger.warning(f"Parse error iter={iteration} error={type(e).__name__}")
                continue

            action = getattr(parsed, "action", None)
            if action == "answer":
                logger.info("Agent completed with answer action")
                return parsed

            if action == "tool":
                tool_calls_str = getattr(parsed, "answer", "")

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

    async def _execute_tool_safe(self, name, args):
        """Safe tool executor that handles invalid syntax without raising."""
        if not name:
            return "Error: Invalid tool call syntax."
        return await self._execute_tool(name, args)

    def _parse_tool_calls(self, answer_str):
        """Parse multiple tool calls from a string separated by newlines."""
        calls = []
        for line in answer_str.splitlines():
             line = line.strip()
             if not line: continue
             
             name, args = self._parse_tool_call(line)
             if name:
                 calls.append((name, args))
        
        # If no calls found using newlines, try parsing the whole thing as one call (backward compatibility)
        if not calls:
             name, args = self._parse_tool_call(answer_str)
             if name:
                 calls.append((name, args))
        
        return calls

    async def _execute_tool(self, tool_name, tool_args):
        """Execute a tool by name (supports both toolkit, sub-agents, and direct callables)."""
        # Find tool
        tool_func = None
        for t in self.tools:
            if callable(t) and t.__name__ == tool_name:
                tool_func = t
                break
            elif isinstance(t, dict) and t.get("name") == tool_name:
                tool_func = t.get("mcp_tool") or t.get("callable")
                break
            elif isinstance(t, BaseContext) and t.name == tool_name:
                tool_func = t
                break
        
        if not tool_func:
            return f"Error: Tool {tool_name} not found."

        try:
            logger.info(f"Executing tool: {tool_name} with {tool_args}")
            
            # 1. Handle Sub-Agents (BaseContext instances)
            if isinstance(tool_func, BaseContext):
                sub_query = tool_args.get("query")
                if not sub_query:
                    # Fallback logic for various arg formats
                    if "args" in tool_args:
                         sub_query = tool_args["args"]
                    else:
                         # Try first value in dict
                         vals = list(tool_args.values())
                         if vals: sub_query = vals[0]

                if not sub_query:
                     return "Error: Sub-agent tool requires a 'query' argument."
                
                result = await tool_func.invoke(str(sub_query))
                
                # Check for answer in result
                if hasattr(result, "answer"):
                    return result.answer
                return str(result)

            # 2. Handle Toolkit / MCP
            if self.toolkit and (hasattr(tool_func, "input_schema") or tool_name in [t.name for t in getattr(self.toolkit, '_tools', [])]):
                 return await self.toolkit.call_tool(tool_name, tool_args)
            
            # 3. Handle Direct Callables
            elif callable(tool_func):
                if inspect.iscoroutinefunction(tool_func):
                    return await tool_func(**tool_args)
                else:
                    return tool_func(**tool_args)
            else:
                return f"Error: Tool {tool_name} is not executable"
        except Exception as e:
            return f"Error executing tool {tool_name}: {e}"

    async def execute_tool_calls(self, tool_calls_str: str):
        """Execute tool calls described in a tool-call string and return an observation string."""
        tool_calls = self._parse_tool_calls(tool_calls_str or "")

        if not tool_calls:
            return f"Error: Could not parse any tool calls from '{tool_calls_str}'. Use tool_name({{\"arg\": \"value\"}}) format."

        safe_calls = []
        for tool_name, tool_args in tool_calls:
            if not tool_name:
                safe_calls.append((None, {"_error": "Invalid tool call syntax."}))
            else:
                safe_calls.append((tool_name, tool_args))

        results = await self.execute_tools_parallel(safe_calls, self._execute_tool_safe)
        return "\n".join(str(res) for res in results)

    def _parse_tool_call(self, call_str):
        """Robustly parse tool_name(args) where args are JSON or keyword pairs."""
        match = re.search(r"(\w+)\((.*)\)", call_str.strip(), re.DOTALL)
        if not match:
            # Fallback for simple name call if it matches regex \w+
            if re.match(r"^\w+$", call_str.strip()):
                return call_str.strip(), {}
            return None, None
            
        name = match.group(1)
        args_str = match.group(2).strip()
        if not args_str:
            return name, {}
            
        # 1. Try JSON parsing
        if args_str.startswith("{") and args_str.endswith("}"):
            try:
                return name, json.loads(args_str)
            except:
                pass
            
        # 2. Try Python-style keyword args
        args = {}
        kv_pairs = re.findall(r"(\w+)\s*=\s*('[^']*'|\"[^\"]*\"|[^,]+)", args_str)
        if kv_pairs:
            for k, v in kv_pairs:
                v = v.strip().strip("'").strip('"')
                # Simple type conversion
                if v.lower() == "true": v = True
                elif v.lower() == "false": v = False
                else:
                    try:
                        if "." in v: v = float(v)
                        else: v = int(v)
                    except:
                        pass
                args[k] = v
            return name, args
            
        # 3. Positional Fallback (e.g. navigate_page("google.com"))
        # Try to find parameter name from tool definition
        param_name = None
        for t in self.tools:
            t_name = None
            if callable(t):
                t_name = t.__name__
            elif isinstance(t, dict):
                t_name = t.get("name")
            elif isinstance(t, BaseContext):
                t_name = t.name
            
            if t_name == name:
                if isinstance(t, dict) and t.get("parameters"):
                    # Extract first param name from parameters string "url: str, ..."
                    param_name = t["parameters"].split(",")[0].split(":")[0].strip().replace("*", "")
                elif callable(t):
                    sig = inspect.signature(t)
                    if sig.parameters:
                        # Skip self/cls for methods if needed, but currently assumes functions/lambdas
                        param_name = list(sig.parameters.keys())[0]
                elif isinstance(t, BaseContext):
                    param_name = "query"
                break
        
        if param_name:
            return name, {param_name: args_str.strip("'").strip('"')}
            
        return name, {"args": args_str}
