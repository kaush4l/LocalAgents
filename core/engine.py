"""
Core context engine for LLM interactions with Observe-Plan-Act style tool calling.
Provides the foundation for multi-agent workflows with streaming events.
"""
import json
import asyncio
import inspect
import re
import logging
import ast
from pathlib import Path
from typing import Any, Callable

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, Field, PrivateAttr

from . import config
from .responses import BaseResponse, ReActResponse, Message

logger = logging.getLogger(__name__)


# =============================================================================
# JINJA2 ENVIRONMENT (cached for performance)
# =============================================================================

_jinja_env: Environment = None


def get_jinja_env(prompts_dir: Path = None) -> Environment:
    """Get or create the cached Jinja2 environment.
    
    Args:
        prompts_dir: Path to the prompts directory
        
    Returns:
        Configured Jinja2 Environment with caching enabled
    """
    global _jinja_env
    
    if _jinja_env is None:
        if prompts_dir is None:
            prompts_dir = Path.cwd() / "prompts"
        
        _jinja_env = Environment(
            loader=FileSystemLoader(str(prompts_dir)),
            autoescape=select_autoescape(enabled_extensions=()),
            auto_reload=False,  # Disable for performance (personal application)
            trim_blocks=True,
            lstrip_blocks=True,
        )
    
    return _jinja_env


class BaseContext(BaseModel):
    """Base context engine for LLM interactions.
    
    Provides:
    - System prompt loading from file (prompts/*.md)
    - Tool instructions generation (callables, dicts, sub-agents)
    - Response model instructions generation
    - Message history management
    - LLM invocation with structured response parsing
    - Real-time event streaming via callbacks
    
    Tool types are determined automatically from the object:
    - BaseContext instances → invoke via agent.invoke()
    - Dict with 'mcp_tool' key → invoke via MCP toolkit
    - Callable functions → invoke directly
    """
    model_config = {"arbitrary_types_allowed": True}
    
    name: str = Field(default="Agent")
    description: str = Field(default="A versatile AI agent.")
    system_instructions: str = Field(default="default")
    model_id: str = Field(default_factory=lambda: config.MODEL_ID)
    tools: list = Field(default_factory=list)
    history: list = Field(default_factory=list)
    response_model: type = Field(default=ReActResponse)
    response_format: str = Field(default="json")
    max_iterations: int = Field(default_factory=lambda: config.MAX_ITERATIONS)
    
    # Cached context components (private)
    _system_prompt: str = PrivateAttr(default="")
    _tool_instructions: str = PrivateAttr(default="")
    _response_instructions: str = PrivateAttr(default="")
    _prompt_root: Path = PrivateAttr(default=Path.cwd() / "prompts")
    _cleanup_callbacks: list[Callable] = PrivateAttr(default_factory=list)
    _tool_registry: dict[str, Callable] = PrivateAttr(default_factory=dict)
    _mcp_toolkit: Any = PrivateAttr(default=None)
    
    def __init__(self, **data):
        """Initialize the context and convert all parameters into cached instructions."""
        super().__init__(**data)
        self._prompt_root = Path.cwd() / "prompts"
        self._tool_registry = self._build_tool_registry(self.tools)
        self._system_prompt = self._convert_system_instructions(self.system_instructions)
        self._tool_instructions = self._convert_tools_to_instructions(self.tools)
        self._response_instructions = self._convert_response_model_to_instructions(
            self.response_model, self.response_format
        )
    
    def _build_tool_registry(self, tools: list) -> dict[str, Callable]:
        """Build a registry mapping tool name -> invoke function.

        This enables O(1) lookup and unified invocation pattern.
        The invoke function encapsulates the tool type logic.
        """
        registry: dict[str, Callable] = {}
        for t in tools:
            if isinstance(t, BaseContext):
                # Context tool: invoke returns coroutine
                registry[t.name] = t.invoke
            elif isinstance(t, dict):
                name = t.get("name", "")
                mcp_tool = t.get("mcp_tool")
                if name and mcp_tool:
                    # MCP tool: create wrapper that uses toolkit
                    # The actual toolkit will be set via set_mcp_toolkit
                    registry[name] = self._create_mcp_invoker(name)
            elif callable(t) and not isinstance(t, type):
                registry[t.__name__] = t
        return registry
    
    def _create_mcp_invoker(self, tool_name: str) -> Callable:
        """Create an invoker function for MCP tools."""
        async def mcp_invoke(**kwargs):
            if self._mcp_toolkit is None:
                return f"Error: MCP toolkit not set for tool {tool_name}"
            return await self._mcp_toolkit.call_tool(tool_name, kwargs)
        return mcp_invoke
    
    def set_mcp_toolkit(self, toolkit):
        """Set the MCP toolkit for this context's MCP tools."""
        self._mcp_toolkit = toolkit

    def get_tool(self, name: str) -> Callable | None:
        """Get tool invoke function by name."""
        return self._tool_registry.get(name)

    
    def _convert_system_instructions(self, system_instructions: str) -> str:
        """Convert system instructions input to prompt text.
        
        System prompts are STATIC .md files that define agent personality,
        tone, and behavior. Dynamic elements (tools, context, messages)
        are injected via render_template.j2 during render().
        """
        if not system_instructions:
            return ""
        
        # Accept explicit file paths
        direct_path = Path(system_instructions)
        
        # Handle .md static files
        if direct_path.suffix == ".md" and direct_path.exists():
            return direct_path.read_text(encoding="utf-8").strip()
        
        # Fallback to prompts/{name}.md
        prompt_path = self._prompt_root / f"{system_instructions}.md"
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8").strip()
        
        # Return as raw string if no file found
        return str(system_instructions)
    
    def _convert_tools_to_instructions(self, tools: list) -> str:
        """Convert a list of tools into text instructions using Jinja2 template.
        
        Handles three types of tools:
        1. BaseContext instances - sub-agent tools (invoke via agent.invoke())
        2. Dict tools - MCP tools formatted as dictionaries
        3. Callable functions - regular Python functions

        Each tool includes: name, type, description, parameters, and invocation example.
        """
        if not tools:
            return ""
        
        tool_data = []
        
        for tool in tools:
            if isinstance(tool, BaseContext):
                # Sub-agent tool
                tool_data.append({
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": "query: str - The task or question to delegate to this agent",
                    "invocation_example": f'{tool.name}({{"query": "your detailed task description"}})',
                })

            elif callable(tool) and not isinstance(tool, (BaseContext, type)):
                # Regular callable function
                name = tool.__name__
                doc = (tool.__doc__ or "No description").strip().split("\n")[0]
                sig = inspect.signature(tool)
                params_lines = []
                for p in sig.parameters.values():
                    p_type = p.annotation.__name__ if p.annotation != inspect.Parameter.empty else "Any"
                    p_default = f" = {p.default!r}" if p.default != inspect.Parameter.empty else ""
                    params_lines.append(f"{p.name}: {p_type}{p_default}")
                params_str = "\n".join(params_lines) if params_lines else "(no parameters)"
                
                # Build example invocation
                example_args = {p.name: f"<{p.name}>" for p in sig.parameters.values()}
                example = f'{name}({json.dumps(example_args)})'
                
                tool_data.append({
                    "name": name,
                    "description": doc,
                    "parameters": params_str,
                    "invocation_example": example,
                })

            elif isinstance(tool, dict):
                # MCP tool formatted as dict
                name = tool.get("name", "unnamed_tool")
                desc = tool.get("description", "No description")
                params = tool.get("parameters", "(see schema)")
                
                tool_data.append({
                    "name": name,
                    "description": desc,
                    "parameters": params,
                    "invocation_example": f'{name}({{"param": "value"}})',
                })

            else:
                # Unknown tool type
                tool_data.append({
                    "name": str(tool),
                    "description": "Unknown tool type",
                    "parameters": "",
                    "invocation_example": f"{tool}()",
                })
        
        # Render using Jinja2 template
        env = get_jinja_env(self._prompt_root)
        template = env.get_template("tools_instructions.j2")
        return template.render(tools=tool_data)
    
    def _convert_response_model_to_instructions(self, response_model, response_format: str) -> str:
        """Convert response model class to instruction text."""
        return response_model.get_instructions(response_format)
    
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
    
    def render(self, user_input: str, context: str = None, response_format: str = "json") -> str:
        """Render the full prompt using render_template.j2 skeleton.
        
        Assembles prompt components in order:
        1. system_prompt (STATIC) - Agent personality/behavior from .md file
        2. context (DYNAMIC) - Observations, environment state
        3. messages (DYNAMIC) - Conversation history
        4. tools (DYNAMIC) - Available tools from tools_instructions.j2
        5. response_instructions (SEMI-STATIC) - JSON format schema
        6. user_input (DYNAMIC) - Current user query
        
        Args:
            user_input: The current user query
            context: Optional dynamic context (observations, environment state)
            response_format: Response format - "json" or "toon"
            
        Returns:
            Fully rendered prompt string
        """
        user_text = "" if user_input is None else str(user_input)
        history = self.format_history(exclude_user_input=user_text)
        
        env = get_jinja_env(self._prompt_root)
        template = env.get_template("render_template.j2")
        return template.render(
            system_prompt=self._system_prompt,
            context=context or "",
            messages=history,
            tools=self._tool_instructions,
            response_instructions=self._response_instructions,
            response_format=response_format,
            user_input=user_text,
        )
    
    async def invoke(self, query: str):
        """Invoke the LLM with the given query and return a parsed response."""
        from . import inference
        
        self.history.append(Message(role="user", content=query))
        
        prompt = self.render(query)
        parsed = await inference.invoke(
            prompt, 
            model_id=self.model_id,
            response_model=self.response_model
        )
        
        # If inference returned a structured object, use its string representation for history
        if hasattr(parsed, "to_json"):
            raw_str = parsed.to_json()
        elif hasattr(parsed, "model_dump_json"):
            raw_str = parsed.model_dump_json()
        else:
            raw_str = str(parsed)
            
        self.history.append(Message(role="assistant", content=raw_str))
        return parsed

    def register_cleanup(self, callback: Callable):
        """Register a cleanup callback to run when this context is closed.

        The callback may be sync or async and will be awaited if needed.
        """
        if callback is None:
            return
        self._cleanup_callbacks.append(callback)

    async def close(self):
        """Close this context and any owned resources.

        Default behavior:
        - Close any context tools (BaseContext) present in `self.tools`.
        - Run registered cleanup callbacks in LIFO order.
        """
        # Close context tools first (owner closes owned contexts)
        for tool in self.tools:
            if isinstance(tool, BaseContext) and hasattr(tool, "close"):
                try:
                    maybe = tool.close()
                    if asyncio.iscoroutine(maybe):
                        await maybe
                except BaseException as e:
                    if isinstance(e, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                        raise
                    logger.error(f"Error closing context tool {getattr(tool, 'name', str(tool))}: {e}")

        # Run cleanup callbacks
        for cb in reversed(self._cleanup_callbacks):
            try:
                result = cb()
                if asyncio.iscoroutine(result):
                    await result
            except BaseException as e:
                if isinstance(e, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                    raise
                logger.error(f"Error during cleanup for {self.name}: {e}")

    def __call__(self, query: str | None = None, **kwargs):
        """Allow contexts to be used as callable tools.

        This enables tool calls like:
        - tool_name("do X")
        - tool_name(query="do X")

        Returns the coroutine from `invoke(...)`.
        """
        resolved = query
        if resolved is None:
            resolved = kwargs.get("query")
        if resolved is None and kwargs:
            # Best-effort: first kwarg value
            resolved = next(iter(kwargs.values()))
        if resolved is None:
            raise ValueError("Context tool requires a 'query' argument")
        return self.invoke(str(resolved))
    
    def _safe_parse_response(self, raw_response):
        """Parse response, returning a safe fallback on errors."""
        try:
            return self.response_model.from_raw(raw_response)
        except Exception as e:
            return self._fallback_response(raw_response, e)
    
    def _fallback_response(self, raw_response, error: Exception):
        """Create a minimal response object that preserves the failure context."""
        error_msg = f"System Error: {type(error).__name__} - {str(error)}"
        
        if issubclass(self.response_model, ReActResponse):
            return self.response_model(
                observation="The system encountered an internal processing error.",
                plan=["Analyze the error message and retry with a different approach."],
                action="answer",
                response=f"An error occurred: {error_msg}. Please try again."
            )
        
        try:
            return self.response_model.model_construct()
        except Exception:
            return BaseResponse.model_construct()


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
        return getattr(result, "response", str(result))
    
    async def invoke(self, query: str):
        """Invoke with ReAct loop until an answer or max iterations reached."""
        from . import inference
        
        self.history.append(Message(role="user", content=query))
        last_parsed = None
        tool_call_history = {}
        
        # If this is a sub-agent (not orchestrator), we might want to cap history
        # to prevent context-leakage between unrelated tasks.
        if self.name != "orchestrator" and len(self.history) > 10:
            logger.info(f"Capping history for sub-agent {self.name} to prevent loops.")
            # Keep system (if first) + last few exchanges
            self.history = self.history[:1] + self.history[-6:]
        
        for iteration in range(max(1, self.max_iterations)):
            prompt = self.render(query)
            
            try:
                parsed = await inference.invoke(
                    prompt,
                    model_id=self.model_id,
                    response_model=self.response_model
                )
                
                # If for some reason it's still a string (fallback), wrap it
                if isinstance(parsed, str):
                    parsed = self.response_model.from_raw(parsed)
                    
                last_parsed = parsed
                
                # Extract action and response - only these go into history
                # observation/plan fields are discarded (not appended to conversation)
                action = getattr(parsed, "action", None)
                response_text = getattr(parsed, "response", "")
                
                # Condensed history: only action + response (no observation/plan)
                response_short = response_text[:120] + "..." if len(response_text) > 120 else response_text
                condensed = f"[action={action}] {response_short}"
                self.history.append(Message(role="assistant", content=condensed))
            
            except Exception as e:
                observation = f"Format Error: Failed to parse your response. Error: {e}. Follow the RESPONSE PROTOCOL strictly."
                self.history.append(Message(role="user", content=f"Observation: {observation}"))
                # Note: raw_str is no longer defined here in the same way, 
                # but we can pass the error to fallback
                last_parsed = self._fallback_response("Error in inference", e)
                logger.warning(f"Parse/Inference error iter={iteration} error={type(e).__name__}")
                continue
            
            action = getattr(parsed, "action", None)
            
            if action == "answer":
                logger.info("Agent completed with answer action")
                return parsed
            
            if action == "tool":
                tool_response = getattr(parsed, "response", "")
                
                # Normalize response to string for tool parsing
                # Response can be a string or list of tool calls
                if isinstance(tool_response, list):
                    tool_calls_str = "\n".join(str(t) for t in tool_response)
                else:
                    tool_calls_str = str(tool_response)
                
                # Loop Detection
                tool_call_history[tool_calls_str] = tool_call_history.get(tool_calls_str, 0) + 1
                if tool_call_history[tool_calls_str] > 2:
                    observation = f"Error: You have attempted the same tool call {tool_call_history[tool_calls_str]} times. Change your strategy or parameters."
                    logger.warning(f"Loop detected for tool call: {tool_calls_str}")
                else:
                    observation = await self.execute_tool_calls(tool_calls_str)
                
                # Append tool result to history (action + result only)
                observation_short = observation[:200] + "..." if len(observation) > 200 else observation
                logger.info(f"Tool executed: {observation_short[:100]}")
                self.history.append(Message(role="user", content=f"Result: {observation}"))
                continue
            
            break
        
        if last_parsed is None:
            logger.error("Max iterations reached without valid response")
            return self._fallback_response("", RuntimeError("No successful parse"))
        return last_parsed
    
    def _parse_tool_call(self, call_str: str) -> tuple:
        """Parse a single tool call string into (name, args) tuple.
        
        Supports formats:
        1. Regular JSON: tool_name({"arg1": "value"})
        2. Context tool (legacy): await tool_name.invoke("query")
        3. Context tool (preferred): tool_name("query")
        """
        call_str = call_str.strip()
        
        # Pattern 1: await AgentName.invoke("query") - Context engine format
        await_match = re.match(
            r'(?:await\s+)?(\w+)\.invoke\s*\(\s*["\'](.+?)["\']\s*\)\s*$',
            call_str,
            re.DOTALL
        )
        if await_match:
            name = await_match.group(1)
            query = await_match.group(2)
            return name, {"query": query}
        
        # Pattern 2: tool_name({...}) or tool_name(...) - Regular format
        match = re.match(r'(\w+)\s*\((.*)\)\s*$', call_str, re.DOTALL)
        if not match:
            return None, {}
        
        name = match.group(1)
        args_str = match.group(2).strip()
        
        if not args_str:
            return name, {}
        
        # Handle quoted string argument (for backwards compatibility)
        quoted_match = re.match(r'^["\'](.+)["\']$', args_str, re.DOTALL)
        if quoted_match:
            return name, {"query": quoted_match.group(1)}
        
        try:
            # Pre-process: if it looks like single-quoted JSON, try converting to double quotes
            processed_args = args_str
            if "'" in args_str and '"' not in args_str:
                processed_args = args_str.replace("'", '"')
                
            args = json.loads(processed_args)
            return name, args if isinstance(args, dict) else {}
        except json.JSONDecodeError:
            # Try to parse key=value or key:value format
            args = {}
            # Simple regex to find key: value or key=value
            # Matches key="val", key='val', key=val
            pairs = re.findall(r'(\w+)\s*[:=]\s*({.*?}|\[.*?\]|".*?"|\'.*?\'|[^,}]+)', args_str)
            for k, v in pairs:
                args[k.strip()] = v.strip().strip('"\'')

            # If regex failed but there's content, maybe it's just a single string argument
            if not args and args_str:
                # If it's a sub-agent, assume it's the query
                args = {"query": args_str.strip().strip('"\'')}

            return name, args

    def _parse_tool_calls(self, answer_str: str) -> list:
        """Parse multiple tool calls from a string separated by newlines."""
        calls: list[tuple[str, dict]] = []

        # Normalize non-empty lines
        lines = [ln.strip() for ln in (answer_str or "").splitlines() if ln.strip()]
        i = 0
        while i < len(lines):
            line = lines[i]

            # Support:
            # tool_name
            # {"query": "..."}
            if re.fullmatch(r"\w+", line) and (i + 1) < len(lines):
                nxt = lines[i + 1]
                if nxt.startswith("{") and nxt.endswith("}"):
                    try:
                        parsed = json.loads(nxt)
                        if isinstance(parsed, dict):
                            calls.append((line, parsed))
                            i += 2
                            continue
                    except json.JSONDecodeError:
                        pass

            name, args = self._parse_tool_call(line)
            if name:
                calls.append((name, args))
            i += 1

        # If no calls found, try parsing the whole thing as one call
        if not calls:
            name, args = self._parse_tool_call(answer_str)
            if name:
                calls.append((name, args))

        return calls

    def _tool_env(self) -> dict[str, Any]:
        """Build a safe evaluation environment for tool calls.
        
        Returns a dict of tool_name -> invoke_function for use with safe eval.
        """
        return {name: fn for name, fn in self._tool_registry.items() if fn is not None}

    def _ast_is_safe_literal(self, node: ast.AST) -> bool:
        if isinstance(node, ast.Constant):
            return True
        if isinstance(node, (ast.List, ast.Tuple)):
            return all(self._ast_is_safe_literal(elt) for elt in node.elts)
        if isinstance(node, ast.Dict):
            return all(
                (k is None or self._ast_is_safe_literal(k)) and self._ast_is_safe_literal(v)
                for k, v in zip(node.keys, node.values)
            )
        return False

    def _ast_is_safe_call(self, node: ast.AST) -> bool:
        if not isinstance(node, ast.Call):
            return False

        # Allow simple function calls: tool_name(...)
        if isinstance(node.func, ast.Name):
            pass  # Valid: direct function name
        elif isinstance(node.func, ast.Attribute):
            # Allow tool_name.invoke(...) for legacy compatibility
            if not (isinstance(node.func.value, ast.Name) and node.func.attr == "invoke"):
                return False
        else:
            return False

        if len(node.args) > 1:
            return False
        if any(kw.arg is None for kw in node.keywords):
            return False

        for arg in node.args:
            if not self._ast_is_safe_literal(arg):
                return False
        for kw in node.keywords:
            if not self._ast_is_safe_literal(kw.value):
                return False
        return True

    async def _execute_tool_call_expr(self, call_str: str) -> tuple[str, Any]:
        """Execute a tool call expressed as a Python expression.

        Supports expressions like:
        - tool_name("query")
        - tool_name(query="query")
        - tool_name.invoke("query")
        - execute_command(command="dir")
        """
        expr = (call_str or "").strip()
        if expr.startswith("await "):
            expr = expr[len("await "):].strip()

        parsed = ast.parse(expr, mode="eval")
        if not self._ast_is_safe_call(parsed.body):
            raise ValueError("Unsafe or unsupported tool call expression")

        # Determine display name
        if isinstance(parsed.body.func, ast.Name):
            display = parsed.body.func.id
        else:
            display = parsed.body.func.value.id

        env = self._tool_env()
        if display not in env:
            raise ValueError(f"Tool {display} not found")

        result = eval(compile(parsed, filename="<tool_call>", mode="eval"), {"__builtins__": {}}, env)
        if asyncio.iscoroutine(result):
            result = await result
        return display, result

    async def _execute_tool(self, tool_name: str, tool_args: dict) -> str:
        """Execute a tool by name using the unified tool registry.
        
        The registry stores invoke functions directly, so we simply call them.
        The invoke function encapsulates the tool type logic.
        """
        invoke_fn = self.get_tool(tool_name)

        if invoke_fn is None:
            return f"Error: Tool {tool_name} not found."

        try:
            logger.info(f"Executing tool: {tool_name} with {tool_args}")

            # Call the invoke function with the provided arguments
            if inspect.iscoroutinefunction(invoke_fn):
                result = await invoke_fn(**tool_args)
            else:
                result = invoke_fn(**tool_args)
            
            # Handle response objects from sub-agents
            if hasattr(result, "action") and result.action == "tool":
                return f"Error: {tool_name} stopped prematurely: {getattr(result, 'response', str(result))}"
            elif hasattr(result, "response"):
                return str(result.response)
            
            return str(result) if result is not None else ""

        except Exception as e:
            err = f"Error executing tool {tool_name}: {e}"
            logger.error(err)
            return err

    async def execute_tool_calls(self, tool_calls_str: str) -> str:
        """Parse and execute one or more tool calls with parallel execution.
        
        Multiple tool calls on separate lines are executed concurrently
        using asyncio.gather for improved performance.
        
        Supports formats:
        - await agent_name.invoke("query") - for sub-agent context tools (legacy)
        - tool_name({"param": "value"}) - for all tool types (preferred)
        """
        raw = (tool_calls_str or "").strip()
        tool_calls = self._parse_tool_calls(raw)

        # Primary path: Python-expression tool calls via safe AST eval
        # This handles "await agent.invoke('query')" format naturally
        if not tool_calls:
            lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
            if not lines:
                return "Error: Empty tool call."

            # Execute multiple lines in parallel
            async def execute_line(line: str) -> str:
                try:
                    name, result = await self._execute_tool_call_expr(line)
                    if hasattr(result, "response"):
                        return f"{name}: {result.response}"
                    return f"{name}: {result}"
                except Exception as e:
                    return f"Error: Could not parse/execute tool call: {line[:120]} ({type(e).__name__}: {e})"
            
            results = await asyncio.gather(*[execute_line(line) for line in lines])
            return "\n".join(results)

        # Fallback path: parsed tool calls with explicit name/args
        # Execute in parallel using asyncio.gather
        async def execute_parsed(name: str, args: dict) -> str:
            return await self._execute_tool(name, args)
        
        results = await asyncio.gather(*[execute_parsed(name, args) for name, args in tool_calls])
        
        return "\n\n".join(results)
