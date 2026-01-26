"""
Structured response models for the agent system.
Provides both JSON and TOON format support with Pydantic validation.
"""
from __future__ import annotations

import json
import re
from typing import Any, ClassVar, Literal, get_args, get_origin
import inspect

from pydantic import BaseModel, Field

ResponseFormat = Literal["json", "toon"]


class BaseResponse(BaseModel):
    """Base class for structured responses.

    Provides:
    - A self-documenting schema description for prompting.
    - Serialization to instruction-friendly formats (JSON, TOON).
    - Parsing/validation from model output back into a typed object.
    """

    TOON_VERSION: ClassVar[str] = "TOON/1"

    def _render_type(self, ann) -> str:
        origin = get_origin(ann)
        args = get_args(ann)

        if origin is Literal:
            return f"Enum{list(args)}"

        if origin in (list,):
            inner = args[0] if args else Any
            return f"List[{self._render_type(inner)}]"

        if inspect.isclass(ann) and issubclass(ann, BaseModel):
            return ann.__name__

        if hasattr(ann, "__name__"):
            return ann.__name__
        return str(ann)

    def _summarize_field(self, ann, desc: str) -> str:
        type_str = self._render_type(ann)
        return f"{type_str} - {desc}" if desc else type_str

    def _representation_structure_helper(self, model_cls):
        structure = {}

        for name, fld in model_cls.model_fields.items():
            ann = fld.annotation
            desc = fld.description or ""

            origin = get_origin(ann)
            args = get_args(ann)

            if origin in (list,) and args:
                inner = args[0]
                if inspect.isclass(inner) and issubclass(inner, BaseModel):
                    structure[name] = [self._representation_structure_helper(inner)]
                    continue

            if inspect.isclass(ann) and issubclass(ann, BaseModel):
                structure[name] = self._representation_structure_helper(ann)
                continue

            structure[name] = self._summarize_field(ann, desc)

        return structure

    def representation_structure(self) -> str:
        """Pretty-printed, concise schema for instruction prompts."""
        model_cls = self.__class__
        root = self._representation_structure_helper(model_cls)
        return json.dumps(root, indent=4, ensure_ascii=False)

    def instruction_docs(self, response_format: str = "json") -> str:
        """Self-documentation for the specific response format."""
        if response_format == "json":
            return (
                "JSON rules:\n"
                "- Return exactly one JSON object matching the schema.\n"
                "- No extra prose outside the JSON output."
            )

        return (
            "TOON/1 rules:\n"
            "- Start with TOON/1 on first line.\n"
            "- Then one 'key: value' per line.\n"
            "- For string values, use double quotes.\n"
            "- For long/multiline strings, escape newlines as \\n.\n"
            "- No extra prose outside the TOON output."
        )

    def instructions(self, response_format: str = "json") -> str:
        """Prompt snippet describing the response protocol for this model."""
        model_cls = self.__class__
        method_desc = (model_cls.__doc__ or "").strip()
        schema = self.representation_structure()
        docs = self.instruction_docs(response_format)

        if response_format == "json":
            return (
                f"{method_desc}\n\n"
                "RESPONSE FORMAT (JSON):\n"
                "```json\n"
                f"{schema}\n"
                "```\n"
                f"{docs}"
            )

        return (
            f"{method_desc}\n\n"
            "RESPONSE FORMAT (TOON/1):\n"
            "```\n"
            f"{self._toon_template_from_schema()}\n"
            "```\n"
            f"{docs}"
        )

    def _toon_template_from_schema(self) -> str:
        """Generate a TOON template from the model fields."""
        lines = []
        for name, fld in self.__class__.model_fields.items():
            desc = fld.description or ""
            ann = fld.annotation
            if ann == str:
                lines.append(f"{name}: \"<string>\" {desc}")
            else:
                lines.append(f"{name}: <{self._render_type(ann)}> {desc}")
        return "\n".join(lines)

    @classmethod
    def get_instructions(cls, response_format: str = "json") -> str:
        """Class-level instructions without needing an instance."""
        instance = cls.model_construct()
        return instance.instructions(response_format)

    def to_json(self, indent: int = 2) -> str:
        """Concise JSON (excludes None fields)."""
        payload = self.model_dump(exclude_none=True)
        return json.dumps(payload, indent=indent, ensure_ascii=False)

    def to_toon(self) -> str:
        """Serialize to TOON/1 (line-based, instruction-friendly)."""
        data = self.model_dump(exclude_none=True)
        lines = [self.TOON_VERSION]

        for key, value in data.items():
            if isinstance(value, str):
                lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
                continue

            if isinstance(value, (dict, list, bool, int, float)):
                lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
                continue

            if value is None:
                continue

            lines.append(f"{key}: {value}")

        return "\n".join(lines)

    def convert(self, response_format: str) -> str:
        """Generic serializer to a requested format literal."""
        if response_format == "json":
            return self.to_json()
        if response_format == "toon":
            return self.to_toon()
        raise ValueError(f"Unsupported response_format: {response_format}")

    def _strip_code_fences(self, text: str) -> str:
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json|text)?\s*", "", text.strip(), flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text.strip())
        return text.strip()

    def _extract_json_object(self, text: str) -> str:
        text = self._strip_code_fences(text)
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise ValueError("No JSON object found in model output")
        return text[start : end + 1]

    def _parse_toon_dict(self, text: str) -> dict:
        text = self._strip_code_fences(text)
        lines = [ln.rstrip("\r") for ln in text.splitlines()]

        result = {}
        for line in lines:
            line = line.strip()
            if not line or line.startswith("TOON"):
                continue
            if ":" not in line:
                continue

            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()

            try:
                result[key] = json.loads(value)
            except json.JSONDecodeError:
                result[key] = value

        return result

    @classmethod
    def from_raw(cls, raw: Any, response_format: str = "json") -> "BaseResponse":
        """Parse raw model output into a response object."""
        if isinstance(raw, cls):
            return raw

        if isinstance(raw, dict):
            return cls.model_validate(raw)

        if not isinstance(raw, str):
            raw = str(raw)

        instance = cls.model_construct()

        try:
            json_str = instance._extract_json_object(raw)
            data = json.loads(json_str)
            return cls.model_validate(data)
        except (ValueError, json.JSONDecodeError):
            pass

        try:
            data = instance._parse_toon_dict(raw)
            if data:
                return cls.model_validate(data)
        except Exception:
            pass

        return cls.model_construct(answer=raw)


class ReActResponse(BaseResponse):
    """ReAct-style response model for reasoning and action.

    Fields:
    - rephrase: Restate the user's request in your own words
    - reverse: Your step-by-step reasoning about how to approach this
    - action: Either 'tool' to call a tool, or 'answer' to provide final response
    - answer: The tool call (if action=tool) or final response (if action=answer)
    """

    rephrase: str = Field(
        default="",
        description="Restate the user's request in your own words"
    )
    reverse: str = Field(
        default="",
        description="Step-by-step reasoning about how to approach this"
    )
    action: Literal["tool", "answer"] = Field(
        default="answer",
        description="Either 'tool' to call a tool, or 'answer' for final response"
    )
    answer: str = Field(
        default="",
        description="Tool call (if action=tool) or final answer (if action=answer)"
    )

    @classmethod
    def from_raw(cls, raw: Any, response_format: str = "json") -> "ReActResponse":
        """Parse raw model output into a ReActResponse."""
        if isinstance(raw, cls):
            return raw

        if isinstance(raw, dict):
            return cls.model_validate(raw)

        if not isinstance(raw, str):
            raw = str(raw)

        instance = cls.model_construct()

        try:
            json_str = instance._extract_json_object(raw)
            data = json.loads(json_str)
            return cls.model_validate(data)
        except (ValueError, json.JSONDecodeError):
            pass

        try:
            data = instance._parse_toon_dict(raw)
            if data:
                return cls.model_validate(data)
        except Exception:
            pass

        return cls(
            rephrase="",
            reverse="",
            action="answer",
            answer=raw.strip()
        )


class ChatMessage(BaseModel):
    """A single message in the conversation history."""
    role: Literal["system", "user", "assistant"] = "user"
    content: str = ""
    name: str | None = None
