"""
Agent engine — abstract ``BaseAgent`` and concrete ``ReActAgent``.

``BaseAgent`` provides:
    • Tool map construction (functions, sub-agents, MCP tools)
    • Prompt rendering (system instructions + context + tools + response format)
    • Observability hooks
    • Conversation history management
    • Inference object (attached in __init__ from model_id)

``ReActAgent`` implements the ReAct loop:
    observe → think → plan → act (tool call or final answer)
"""

from __future__ import annotations

import asyncio as _asyncio_mod
import inspect
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, Field, PrivateAttr

from . import observability
from .responses import Message, ReActResponse

_DEFAULT_MODEL_ID = "lms/qwen/qwen3-vl-30b"
_DEFAULT_RESPONSE_FORMAT = "toon"
_DEFAULT_MAX_ITERATIONS = 8

# ── RuntimeObject — lifecycle base for long-lived services ─────────────────

logger = logging.getLogger(__name__)


class RuntimeObject(BaseModel):
    """Shared lifecycle contract for runtime objects (STS, Telegram, etc.)."""

    model_config = {"arbitrary_types_allowed": True}

    name: str = Field(default="runtime_object")

    _is_initialized: bool = PrivateAttr(default=False)
    _lifecycle_lock: _asyncio_mod.Lock = PrivateAttr(default_factory=_asyncio_mod.Lock)

    @property
    def is_initialized(self) -> bool:
        return self._is_initialized

    async def initialize(self) -> "RuntimeObject":
        async with self._lifecycle_lock:
            if self._is_initialized:
                return self
            result = self._initialize_impl()
            if inspect.isawaitable(result):
                await result
            self._is_initialized = True
            return self

    async def shutdown(self) -> None:
        async with self._lifecycle_lock:
            if not self._is_initialized:
                return
            result = self._shutdown_impl()
            if inspect.isawaitable(result):
                await result
            self._is_initialized = False

    def _initialize_impl(self) -> Any:
        """Override in subclass for startup logic."""

    def _shutdown_impl(self) -> Any:
        """Override in subclass for teardown logic."""


# ═════════════════════════════════════════════════════════════════════════════
# Multimodality
# ═════════════════════════════════════════════════════════════════════════════


class Multimodality(BaseModel):
    """Non-text inputs to attach to an inference call."""

    modality_type: str = Field(description="e.g. 'image'")
    collection: list[Any] = Field(default_factory=list)


# ═════════════════════════════════════════════════════════════════════════════
# BaseAgent (abstract)
# ═════════════════════════════════════════════════════════════════════════════


class BaseAgent(BaseModel):
    """Abstract base for all agents.

    Every downstream agent automatically gets:
        • System prompt loaded from ``agents/prompts/{name}.md``
        • Tool map built from the ``tools`` list
        • Structured response enforcement via ``response_model``
        • Inference object attached from ``model_id``
        • Conversation history management
    """

    model_config = {"arbitrary_types_allowed": True}

    name: str = Field(default="Agent")
    description: str = Field(default="A versatile AI agent.")
    system_instructions: str = Field(default="default")
    model_id: str = Field(default_factory=lambda: os.getenv("MODEL_ID", _DEFAULT_MODEL_ID))
    tools: list = Field(default_factory=list)
    history: list[Message] = Field(default_factory=list)
    response_model: type = Field(default=ReActResponse)
    response_format: str = Field(default_factory=lambda: os.getenv("RESPONSE_FORMAT", _DEFAULT_RESPONSE_FORMAT))

    _tools_map: dict[str, Callable] = PrivateAttr(default_factory=dict)
    _system_instructions: str = PrivateAttr(default="")
    _tools_instructions: str = PrivateAttr(default="")
    _response_instructions: str = PrivateAttr(default="")
    _multimodal_collectors: list[Callable[..., Any]] = PrivateAttr(default_factory=list)
    _inference: Any = PrivateAttr(default=None)

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        self._tools_map = self._build_tools_map(self.tools)
        self._system_instructions = self._load_system_instructions()
        self._tools_instructions = self._format_tools_instructions()
        self._response_instructions = self.response_model.get_instructions(self.response_format)

        # Attach inference object from model_id
        from .inference import get_implementation

        self._inference = get_implementation(self.model_id)

    # ── tool map ─────────────────────────────────────────────────────────

    def _build_tools_map(self, tools: list) -> dict[str, Callable]:
        tools_map: dict[str, Callable] = {}
        for tool in tools:
            if isinstance(tool, BaseAgent):

                async def _wrap(inputs: dict, agent: BaseAgent = tool) -> Any:
                    return await agent.invoke(inputs.get("query", ""))

                _wrap.__name__ = tool.name
                tools_map[tool.name] = _wrap
            elif callable(tool) and not isinstance(tool, type):
                tools_map[tool.__name__] = tool
        return tools_map

    # ── prompt loading ───────────────────────────────────────────────────

    def _load_system_instructions(self) -> str:
        prompt_path = Path.cwd() / "agents" / "prompts" / f"{self.system_instructions}.md"
        return prompt_path.read_text(encoding="utf-8").strip() if prompt_path.exists() else ""

    def _format_tools_instructions(self) -> str:
        if not self.tools:
            return ""
        docs: list[str] = []
        for tool in self.tools:
            if isinstance(tool, BaseAgent):
                docs.append(
                    f"## {tool.name}\n"
                    f"**Type**: Sub-Agent\n"
                    f"**Description**:\n{tool.description}\n"
                    f'**Usage**: {tool.name}({{"query": "your detailed task description"}})\n'
                )
            elif callable(tool):
                doc = (tool.__doc__ or "").strip().split("\n")[0]
                docs.append(
                    f"## {tool.__name__}\n**Type**: Tool\n**Description**:\n{doc}\n"
                    f'**Usage**: {tool.__name__}({{"key": "value"}})\n'
                )
        if not docs:
            return ""
        return (
            "## AVAILABLE TOOLS\n\n" + "\n".join(docs) + "\n\n## TOOL INVOCATION FORMAT\n\n"
            'Use exact format: tool_name({"param": "value"})\n'
            'For sub-agents: agent_name({"query": "task description"})\n'
        )

    # ── history ──────────────────────────────────────────────────────────

    def format_history(self, limit: int = 20) -> str:
        if not self.history:
            return ""
        recent = self.history[-limit:]
        lines = ["## CONVERSATION HISTORY", ""]
        lines.extend(f"{i}. [{msg.role.upper()}]: {msg.content}" for i, msg in enumerate(recent, 1))
        return "\n".join(lines)

    # ── prompt rendering ─────────────────────────────────────────────────

    def render(self, user_input: str, context: str | None = None) -> str:
        parts: list[str] = []

        if self._system_instructions:
            parts.append(self._system_instructions)

        now_local = datetime.now().astimezone()
        now_utc = datetime.now(timezone.utc)
        ctx = (
            "## CONTEXT\n"
            f"Current local time: {now_local.isoformat()}\n"
            f"Current UTC time: {now_utc.isoformat().replace('+00:00', 'Z')}"
        )
        parts.append(f"{ctx}\n\n{context}" if context else ctx)

        if history_text := self.format_history():
            parts.append(history_text)
        if self._tools_instructions:
            parts.append(self._tools_instructions)

        parts.append(self._response_instructions)
        parts.append(f"## CURRENT REQUEST\n\n{user_input}")
        return "\n\n".join(parts)

    # ── multimodal ───────────────────────────────────────────────────────

    async def _collect_multimodal_inputs(self) -> list[Multimodality]:
        results: list[Multimodality] = []
        for collector in self._multimodal_collectors:
            try:
                val = collector()
                if inspect.isawaitable(val):
                    val = await val
                if isinstance(val, Multimodality):
                    results.append(val)
            except Exception:
                continue
        return results

    # ── tool execution ───────────────────────────────────────────────────

    async def execute_tool(self, tool_name: str, inputs: dict, metadata: dict | None = None) -> str:
        """Execute a tool by name. Never raises — returns error string on failure."""
        trace_id = observability.current_trace_id()
        observability.log_event(
            "tool_start",
            agent=self.name,
            trace_id=trace_id,
            meta={"tool": tool_name, "inputs": inputs, **(metadata or {})},
        )
        start = time.perf_counter()

        try:
            fn = self._tools_map[tool_name]
            result = await fn(inputs) if inspect.iscoroutinefunction(fn) else fn(inputs)
            duration_ms = int((time.perf_counter() - start) * 1000)
            result_str = str(result)
            observability.log_event(
                "tool_end",
                agent=self.name,
                trace_id=trace_id,
                message=result_str[:500],
                meta={"tool": tool_name, "duration_ms": duration_ms},
            )
            return result_str
        except Exception as e:
            duration_ms = int((time.perf_counter() - start) * 1000)
            error_msg = f"Error executing {tool_name}: {e}"
            observability.log_event(
                "tool_error",
                agent=self.name,
                trace_id=trace_id,
                status="error",
                meta={"tool": tool_name, "duration_ms": duration_ms, "error": str(e)},
            )
            logger.error(error_msg)
            return error_msg

    # ── tool call parsing ────────────────────────────────────────────────

    @staticmethod
    def parse_tool_calls(response_text: str | list) -> list[tuple[str, dict]]:
        """Parse ``tool_name({"key": "val"})`` patterns from response text."""
        raw = " ".join(str(item) for item in response_text) if isinstance(response_text, list) else str(response_text)
        results: list[tuple[str, dict]] = []
        for match in re.finditer(r"(\w+)\s*\(\s*(\{.*?\})\s*\)", raw, re.DOTALL):
            try:
                args = json.loads(match.group(2))
            except json.JSONDecodeError:
                args = {"query": match.group(2)}
            results.append((match.group(1), args))
        return results

    # ── invoke contract ──────────────────────────────────────────────────

    async def invoke(self, query: str) -> Any:
        """Run the agent's main loop. Must be implemented by subclasses."""
        raise NotImplementedError(f"{self.__class__.__name__} must implement invoke().")


# ═════════════════════════════════════════════════════════════════════════════
# ReActAgent (concrete)
# ═════════════════════════════════════════════════════════════════════════════


class ReActAgent(BaseAgent):
    """Concrete agent implementing the ReAct loop.

    observe → think → plan → act → (tool result | final answer)
    Repeats until ``action == "answer"`` or max iterations reached.
    """

    max_iterations: int = Field(
        default_factory=lambda: int(os.getenv("MAX_ITERATIONS", str(_DEFAULT_MAX_ITERATIONS)))
    )

    async def invoke(self, query: str) -> Any:
        # Clear history between invocations to prevent cross-request pollution
        self.history.clear()

        with observability.trace_scope(
            self.name,
            query,
            meta={"model_id": self.model_id, "response_format": self.response_format},
        ) as trace_id:
            self.history.append(Message(role="user", content=query))

            max_iters = self.max_iterations
            for iteration in range(max_iters):
                idx = iteration + 1
                prompt = self.render(query)
                multimodal = await self._collect_multimodal_inputs()

                observability.log_event(
                    "iteration_start",
                    agent=self.name,
                    trace_id=trace_id,
                    meta={"iteration": idx, "prompt_chars": len(prompt)},
                )

                try:
                    start = time.perf_counter()
                    parsed = await self._inference.invoke(
                        prompt,
                        model_id=self.model_id,
                        response_model=self.response_model,
                        multimodal=multimodal,
                    )
                    duration_ms = int((time.perf_counter() - start) * 1000)

                    action = getattr(parsed, "action", "answer")
                    response_text = getattr(parsed, "response", "")
                    thinking = getattr(parsed, "thinking", "")
                    response_str = str(response_text[0]) if isinstance(response_text, list) else str(response_text)

                    observability.log_event(
                        "model_end",
                        agent=self.name,
                        trace_id=trace_id,
                        meta={"iteration": idx, "duration_ms": duration_ms, "action": action},
                        message=response_str,
                    )
                    if thinking:
                        observability.log_event(
                            "thought",
                            agent=self.name,
                            trace_id=trace_id,
                            meta={"iteration": idx},
                            message=str(thinking),
                        )

                    self.history.append(Message(role="assistant", content=f"[action={action}] {response_str[:120]}"))

                    # ── final answer ─────────────────────────────────────
                    if action == "answer":
                        answer_text = response_str or str(thinking) or str(getattr(parsed, "observation", ""))
                        observability.log_event(
                            "answer",
                            agent=self.name,
                            trace_id=trace_id,
                            meta={"iteration": idx},
                            message=answer_text,
                        )
                        return parsed

                    # ── tool calls ───────────────────────────────────────
                    if action == "tool":
                        tool_calls = self.parse_tool_calls(response_text)
                        if not tool_calls:
                            observation = "Error: No valid tool call found in response"
                            observability.log_event(
                                "tool_parse_error",
                                agent=self.name,
                                trace_id=trace_id,
                                meta={"iteration": idx},
                                message=response_str,
                            )
                        else:
                            observations: list[str] = []
                            for tool_name, inputs in tool_calls:
                                if not tool_name or tool_name not in self._tools_map:
                                    available = ", ".join(self._tools_map.keys()) or "none"
                                    observations.append(f"{tool_name}: Tool not found. Available: {available}")
                                    continue
                                result = await self.execute_tool(tool_name, inputs, metadata={"iteration": idx})
                                observations.append(f"{tool_name}: {result}")
                            observation = "\n".join(observations)

                        self.history.append(Message(role="user", content=f"Result: {observation}"))

                except Exception as e:
                    logger.error("Iteration %d error: %s", idx, e)
                    observability.log_event(
                        "error",
                        agent=self.name,
                        trace_id=trace_id,
                        status="error",
                        meta={"iteration": idx, "error": str(e)},
                    )
                    self.history.append(Message(role="user", content=f"Error: {e}"))

            # Max iterations fallback
            observability.log_event(
                "max_iterations",
                agent=self.name,
                trace_id=trace_id,
                status="error",
                meta={"max_iterations": max_iters},
            )
            return ReActResponse(
                observation="Max iterations reached",
                plan=[],
                action="answer",
                response="I couldn't complete the task within the allowed iterations.",
            )
