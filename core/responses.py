from __future__ import annotations

import inspect
import json
import re
from typing import Any, ClassVar, Literal, get_args, get_origin

from pydantic import BaseModel, Field

ResponseFormat = Literal["json", "toon"]


class BaseResponse(BaseModel):
    """Base class for structured responses.

    This model provides:
    - A self-documenting, *concise* schema description for prompting.
    - Serialization to instruction-friendly formats (JSON, TOON/1).
    - Parsing/validation from model output back into a typed object.
    """

    TOON_VERSION: ClassVar[str] = "TOON/1"

    # ------------------------
    # Instructions / docs
    # ------------------------
    def _render_type(self, ann):
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

    def _summarize_field(self, ann, desc):
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

    def representation_structure(self):
        """Pretty-printed, concise schema for instruction prompts (not a dump of values)."""
        model_cls = self.__class__
        root = self._representation_structure_helper(model_cls)
        return json.dumps(root, indent=4, ensure_ascii=False)

    def instruction_docs(self, response_format="json"):
        """Self-documentation for the specific response format."""
        if response_format == "json":
            return (
                "JSON rules:\n"
                "- Return exactly one JSON object matching the schema.\n"
                "- No extra prose outside the JSON output."
            )
        
        return (
            "TOON/1 rules:\n"
            "- Then one 'key: value' per line.\n"
            "- For string values, ALWAYS use a JSON string wrapped in double quotes (e.g., key: \"text\").\n"
            "- For long/multiline strings, keep ONE LINE by escaping newlines as \\n inside the double-quoted string.\n"
            "  Example: answer: \"Line 1\\nLine 2\"\n"
            "- If you must use literal multi-line text, you MAY use a block: key: | (or key: |-) then indent subsequent lines by 2 spaces.\n"
            "- Inside the answer text, prefer single quotes for dialogue so you don't break the outer double quotes.\n"
            "- No extra prose outside the TOON output."
        )

    def instructions(self, response_format="json"):
        """Prompt snippet describing the strict response protocol for this model."""
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

    def _toon_template_from_schema(self):
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
    def get_instructions(cls, response_format="json"):
        """Class-level instructions without needing an instance."""
        instance = cls.model_construct()
        return instance.instructions(response_format)

    # ------------------------
    # Serialization
    # ------------------------
    def to_json(self, indent=2):
        """Concise JSON (excludes None fields)."""
        payload = self.model_dump(exclude_none=True)
        return json.dumps(payload, indent=indent, ensure_ascii=False)

    def to_toon(self):
        """Serialize to TOON/1 (line-based, instruction-friendly)."""
        data = self.model_dump(exclude_none=True)
        lines = [self.TOON_VERSION]

        for key, value in data.items():
            if isinstance(value, str):
                # Always emit JSON-quoted strings so newlines are safely represented as \n
                lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
                continue

            if isinstance(value, (dict, list, bool, int, float)):
                lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
                continue

            if value is None:
                continue

            lines.append(f"{key}: {value}")

        return "\n".join(lines)

    def convert(self, response_format):
        """Generic serializer to a requested format literal ('json' or 'toon')."""
        if response_format == "json":
            return self.to_json()
        if response_format == "toon":
            return self.to_toon()
        raise ValueError(f"Unsupported response_format: {response_format}")

    # ------------------------
    # Parsing (model output -> object)
    # ------------------------
    def _strip_code_fences(self, text):
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json|text)?\s*", "", text.strip(), flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text.strip())
        return text.strip()

    def _extract_json_object(self, text):
        text = self._strip_code_fences(text)
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise ValueError("No JSON object found in model output")
        return text[start : end + 1]

    def _parse_toon_dict(self, text):
        text = self._strip_code_fences(text)
        lines = [ln.rstrip("\r") for ln in text.splitlines()]
        lines = [ln for ln in lines if ln.strip()]

        if not lines:
            raise ValueError("Empty TOON output")

        if lines[0].strip().upper() in {"TOON/1", "TOON1", "TOON"}:
            i = 1
        else:
            # Be tolerant if the model omitted the header.
            i = 0

        # Get field types from the model to preserve string types
        field_types = {}
        for name, fld in self.__class__.model_fields.items():
            field_types[name] = fld.annotation

        result = {}
        while i < len(lines):
            line = lines[i]
            if ":" not in line:
                raise ValueError(f"Invalid TOON line (missing ':'): {line}")

            key, rest = line.split(":", 1)
            key = key.strip()
            value = rest.lstrip()

            # Multi-line strings.
            # Be tolerant to YAML-style chomping indicators: |, |-, |+
            if value.strip() in {"|", "|-", "|+"}:
                i += 1
                block = []
                while i < len(lines):
                    next_line = lines[i]
                    if next_line.startswith("  "):
                        block.append(next_line[2:])
                        i += 1
                        continue
                    break
                result[key] = "\n".join(block)
                continue

            # Check if this field expects a string type
            expected_type = field_types.get(key)
            if expected_type == str:
                # Prefer decoding JSON-quoted strings so \n becomes an actual newline.
                # (Also keeps embedded single quotes in dialogue safe.)
                v = value.strip()
                if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
                    try:
                        result[key] = json.loads(v)
                    except Exception:
                        result[key] = value
                else:
                    result[key] = value
            else:
                # Try JSON parse for structured scalars
                try:
                    parsed = json.loads(value)
                    result[key] = parsed
                except Exception:
                    result[key] = value
            i += 1

        return result

    def parse(self, text, response_format="json"):
        """Parse model output into a validated response object."""
        model_cls = self.__class__
        if response_format == "json":
            payload = self._extract_json_object(text)
            return model_cls.model_validate_json(payload)
        if response_format == "toon":
            payload = self._parse_toon_dict(text)
            return model_cls.model_validate(payload)
        raise ValueError(f"Unsupported response_format: {response_format}")

    @classmethod
    def from_raw(cls, text, response_format="json"):
        """Class method to parse raw model output into a validated response object."""
        instance = cls.model_construct()
        return instance.parse(text, response_format)


class ReActResponse(BaseResponse):
    """ReAct-style response model.

    Use this response when you want the model to either:
    - request a tool call, or
    - provide a final user-facing answer.
    """
    rephrase: str = Field(
        description="Restate the request, adding clarifying context while staying faithful to intent."
    )
    reverse: str = Field(
        description="Think backwards: identify assumptions, edge cases, and verification steps needed."
    )
    action: Literal["tool", "answer"] = Field(
        description="Either 'tool' for a tool call or 'answer' for the final result."
    )
    answer: str = Field(
        description="Tool call (if action='tool') or user-visible answer (if action='answer')."
    )