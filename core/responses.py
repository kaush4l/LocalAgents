"""
Structured response models for LLM output parsing.

Hierarchy:
    BaseResponse          — parsing logic (JSON / TOON / fallback)
    └─ ReActResponse      — observe-think-plan-act fields
    Message               — single conversation turn
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal, get_origin

from pydantic import BaseModel, Field, model_validator


class BaseResponse(BaseModel):
    """Base structured response with multi-format parsing.

    Subclasses only need to declare fields — parsing and instruction
    generation are fully inherited.
    """

    # ── shared helpers ───────────────────────────────────────────────────

    @staticmethod
    def _strip_wrapping_quotes(value: str) -> str:
        text = value.strip()
        if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
            return text[1:-1]
        return value

    # ── instruction generation ───────────────────────────────────────────

    @classmethod
    def get_instructions(cls, fmt: str = "json") -> str:
        """Generate response-format instructions for inclusion in prompts."""
        fields_doc = []
        for name, field in cls.model_fields.items():
            desc = field.description or ""
            annotation = field.annotation
            origin = get_origin(annotation)
            if origin is list:
                type_str = "list"
            elif annotation is str:
                type_str = "string"
            elif hasattr(annotation, "__args__"):
                type_str = " | ".join(str(a) for a in annotation.__args__)
            else:
                type_str = str(annotation)
            fields_doc.append(f"- **{name}** ({type_str}): {desc}")

        fields_text = "\n".join(fields_doc)
        field_names = list(cls.model_fields.keys())

        if fmt == "json":
            return (
                "## RESPONSE FORMAT\n\n"
                "Respond with a single JSON object containing these fields:\n\n"
                f"{fields_text}\n\n"
                "Important: Output ONLY the JSON object, no markdown fences.\n"
            )

        # TOON format
        examples = {
            "plan": "plan: [step one, step two]",
            "action": "action: answer",
            "response": "response: <final answer OR tool call>",
        }
        example_block = "\n\n".join(examples.get(n, f"{n}: <your {n} here>") for n in field_names)

        return (
            "## RESPONSE FORMAT\n\n"
            "You MUST respond with EXACTLY these fields, in order, one per block.\n"
            "Each field starts on its own line as `field_name: value`.\n"
            "Separate fields with a blank line.\n"
            f"The ONLY valid field names are: {', '.join(field_names)}.\n\n"
            f"### Field descriptions\n\n{fields_text}\n\n"
            "### Rules\n\n"
            "1. Write the field name in lowercase, followed by a colon and a space, then the value.\n"
            "2. Multi-line values: just keep writing on the next lines — do NOT repeat the field name.\n"
            "3. List fields: use bracket notation [item1, item2].\n"
            "4. Do NOT add markdown bold (**), bullets (-), or any decoration to field names.\n"
            "5. Do NOT use any field names other than the ones listed above.\n"
            "6. CRITICAL — action values: The 'action' field MUST be EXACTLY the literal word 'tool' or EXACTLY the literal word "
            "'answer'. Never write a tool name in 'action'. For example, 'action: web_search' is ALWAYS WRONG and will "
            "break the system. The ONLY valid values are 'action: tool' and 'action: answer'.\n"
            "7. CRITICAL — tool calls: When you want to call a tool, write 'action: tool' and place the full "
            'tool invocation in the \'response\' field as tool_name({"key": "value"}).\n\n'
            "### Correct vs Wrong\n\n"
            "CORRECT:\n"
            "```\n"
            "action: tool\n\n"
            'response: web_search({"query": "latest Python release"})\n'
            "```\n\n"
            "WRONG (never do this):\n"
            "```\n"
            "action: web_search\n\n"
            'response: web_search({"query": "latest Python release"})\n'
            "```\n\n"
            f"### Full Example\n\n```\n{example_block}\n```\n"
        )

    # ── internal parsing helpers ─────────────────────────────────────────

    @staticmethod
    def _extract_json_object(text: str) -> str:
        depth, start = 0, -1
        for i, ch in enumerate(text):
            if ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and start >= 0:
                    return text[start : i + 1]
        raise ValueError("No JSON object found")

    @staticmethod
    def _clean_toon_key(raw: str) -> str:
        k = raw.strip()
        k = re.sub(r"^[-*]+\s*", "", k)
        k = re.sub(r"^\d+\.\s*", "", k)
        return k.strip("*").strip().lower()

    def _parse_toon(self, text: str) -> dict:
        """Two-pass key-aware TOON parser."""
        known_fields = set(self.__class__.model_fields.keys())
        aliases = {"tool": "response"}
        lines = text.splitlines()

        # Pass 1 — find field start positions
        field_starts: list[tuple[int, str, str]] = []
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if ":" not in stripped:
                continue
            raw_key, _, val = stripped.partition(":")
            cleaned = self._clean_toon_key(raw_key)
            cleaned = aliases.get(cleaned, cleaned)
            if cleaned in known_fields:
                field_starts.append((idx, cleaned, val.strip()))

        if not field_starts:
            return {}

        # Pass 2 — extract values between field boundaries
        data: dict[str, Any] = {}
        for i, (start_idx, field_name, first_val) in enumerate(field_starts):
            end_idx = field_starts[i + 1][0] if i + 1 < len(field_starts) else len(lines)
            value_parts = [first_val] if first_val else []
            value_parts.extend(lines[start_idx + 1 : end_idx])
            value = "\n".join(value_parts).strip()
            self._set_toon_value(data, field_name, value)

        # Coerce any invalid action value to "tool".
        # Handles patterns like "action: web_search" (bare tool name) as well as
        # "action: web_search({...})" (inline tool call).
        action = data.get("action", "").strip()
        if action and action not in ("tool", "answer"):
            # If the invalid value itself looks like a tool call, move it to response
            if "(" in action or "{" in action:
                if not data.get("response"):
                    data["response"] = action
            # Always force action to "tool" for any non-"answer" invalid value
            data["action"] = "tool"

        return data

    def _parse_bracket_list(self, value: str) -> list[str] | None:
        value = value.strip()
        if not (value.startswith("[") and value.endswith("]")):
            return None
        inner = value[1:-1].strip()
        if not inner:
            return []
        items: list[str] = []
        current: list[str] = []
        depth = 0
        for char in inner:
            if char in "({[":
                depth += 1
                current.append(char)
            elif char in ")}]":
                depth -= 1
                current.append(char)
            elif char == "," and depth == 0:
                items.append("".join(current).strip())
                current = []
            else:
                current.append(char)
        if current:
            items.append("".join(current).strip())
        return items

    def _set_toon_value(self, data: dict, key: str, value: str) -> None:
        bracket_list = self._parse_bracket_list(value)
        if bracket_list is not None:
            data[key] = bracket_list
            return
        match = re.match(r"^(\w+)\[(\d+)\]$", key)
        if match:
            base_key, idx = match.group(1), int(match.group(2))
            lst = data.setdefault(base_key, [])
            while len(lst) <= idx:
                lst.append("")
            lst[idx] = value
        else:
            data[key] = value

    def _coerce_list_fields(self, data: dict, model_cls: type) -> dict:
        coerced = dict(data)
        for field_name, field in model_cls.model_fields.items():
            if get_origin(field.annotation) is not list:
                continue
            value = coerced.get(field_name)
            if not isinstance(value, str):
                continue
            parsed = self._parse_bracket_list(value)
            if parsed is not None:
                coerced[field_name] = parsed
            else:
                lines = [ln.strip() for ln in value.splitlines() if ln.strip()]
                coerced[field_name] = [re.sub(r"^\s*(\d+\.|\-|\*)\s*", "", ln).strip() for ln in lines]
        return coerced

    # ── public parser ────────────────────────────────────────────────────

    @classmethod
    def from_raw(cls, raw: Any) -> "BaseResponse":
        """Parse raw LLM output into a typed response.

        Tries: already-correct type → dict → JSON → TOON → fallback.
        """
        if isinstance(raw, cls):
            return raw
        if isinstance(raw, dict):
            return cls.model_validate(raw)
        if not isinstance(raw, str):
            raw = str(raw)

        instance = cls.model_construct()

        # JSON
        try:
            json_str = instance._extract_json_object(raw)
            data = json.loads(json_str)
            if set(cls.model_fields.keys()) & set(data.keys()):
                return cls.model_validate(data)
        except Exception:
            pass

        # TOON
        try:
            data = instance._parse_toon(raw)
            if data:
                try:
                    return cls.model_validate(data)
                except Exception:
                    return cls.model_validate(instance._coerce_list_fields(data, cls))
        except Exception:
            pass

        # Fallback
        fallback = {"response": raw.strip()} if "response" in cls.model_fields else {}
        try:
            return cls.model_validate(fallback)
        except Exception:
            return cls.model_construct(**fallback)


class ReActResponse(BaseResponse):
    """Observe → Think → Plan → Act response model."""

    observation: str = Field(
        default="",
        description="One short sentence about current context, key facts, or constraints.",
    )
    thinking: str = Field(
        default="",
        description="In-depth reasoning and analysis. Must be safe to log.",
    )
    plan: list[str] = Field(
        default_factory=list,
        description="0-3 short, concrete next steps. Use [] when obvious.",
    )
    action: Literal["tool", "answer"] = Field(
        default="answer",
        description="'tool' to invoke a tool, 'answer' to provide the final response.",
    )
    response: str | list[str] = Field(
        default="",
        description="If action='tool': tool call(s). If action='answer': final response text.",
    )

    @model_validator(mode="after")
    def _normalize_fields(self) -> "ReActResponse":
        if isinstance(self.observation, str):
            self.observation = self._strip_wrapping_quotes(self.observation)
        if isinstance(self.thinking, str):
            self.thinking = self._strip_wrapping_quotes(self.thinking)
        if isinstance(self.response, str):
            self.response = self._strip_wrapping_quotes(self.response)
        elif isinstance(self.response, list):
            self.response = [
                self._strip_wrapping_quotes(item) if isinstance(item, str) else item for item in self.response
            ]
        return self


class Message(BaseModel):
    """A single message in the conversation history."""

    role: Literal["system", "user", "assistant"]
    content: str
