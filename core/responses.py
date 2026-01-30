"""
Structured response models for the agent system.
Provides JSON format support with Pydantic validation.
"""
from __future__ import annotations

import json
import re
from typing import Any, Literal, get_args, get_origin
import inspect

from pydantic import BaseModel, Field


class BaseResponse(BaseModel):
    """Base class for structured responses.

    Provides:
    - A self-documenting schema description for prompting.
    - Serialization to JSON format.
    - Parsing/validation from model output back into a typed object.
    """

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

    def instruction_docs(self) -> str:
        """Self-documentation for JSON response format."""
        return (
            "JSON rules:\n"
            "- Return exactly one JSON object matching the schema.\n"
            "- No extra prose outside the JSON output."
        )

    def toon_instruction_docs(self) -> str:
        """Self-documentation for TOON response format."""
        return (
            "TOON/1 rules:\n"
            "- One key: value per line.\n"
            "- Lists use brackets: plan: [step1, step2, step3]\n"
            "- For parallel tools: response: [tool_a({...}), tool_b({...})]\n"
            "- No quotes around values unless part of the value itself.\n"
            "- No extra prose outside the TOON block."
        )

    def _toon_representation_structure_helper(self, model_cls, prefix: str = "") -> list[str]:
        """Generate TOON format field documentation."""
        lines = []
        for name, fld in model_cls.model_fields.items():
            ann = fld.annotation
            desc = fld.description or ""
            type_str = self._render_type(ann)
            key = f"{prefix}{name}" if prefix else name
            lines.append(f"{key}: <{type_str}> - {desc}")
        return lines

    def toon_representation_structure(self) -> str:
        """TOON format schema representation."""
        model_cls = self.__class__
        lines = self._toon_representation_structure_helper(model_cls)
        return "\n".join(lines)

    def instructions(self, response_format: str = "json") -> str:
        """Prompt snippet describing the response protocol for this model."""
        model_cls = self.__class__
        method_desc = (model_cls.__doc__ or "").strip()

        if response_format == "toon":
            schema = self.toon_representation_structure()
            docs = self.toon_instruction_docs()
            return (
                f"{method_desc}\n\n"
                "RESPONSE FORMAT (TOON/1):\n"
                "```\n"
                f"{schema}\n"
                "```\n"
                f"{docs}"
            )
        else:
            schema = self.representation_structure()
            docs = self.instruction_docs()
            return (
                f"{method_desc}\n\n"
                "RESPONSE FORMAT (JSON):\n"
                "```json\n"
                f"{schema}\n"
                "```\n"
                f"{docs}"
            )

    @classmethod
    def get_instructions(cls, response_format: str = "json") -> str:
        """Class-level instructions without needing an instance."""
        instance = cls.model_construct()
        return instance.instructions(response_format)

    def to_json(self, indent: int = 2) -> str:
        """Concise JSON (excludes None fields)."""
        payload = self.model_dump(exclude_none=True)
        return json.dumps(payload, indent=indent, ensure_ascii=False)

    def _strip_code_fences(self, text: str) -> str:
        """Remove markdown code fences from text."""
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json|text)?\s*", "", text.strip(), flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text.strip())
        return text.strip()

    def _extract_json_object(self, text: str) -> str:
        """Extract a JSON object from text, handling code fences."""
        text = self._strip_code_fences(text)
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise ValueError("No JSON object found in model output")
        return text[start : end + 1]

    def _parse_toon(self, text: str) -> dict:
        """Parse TOON/1 format into a dictionary.
        
        TOON format:
        - key: value (one per line)
        - key[idx]: value (for list items)
        - Continuation lines start with whitespace
        """
        text = self._strip_code_fences(text)
        data = {}
        current_key = None
        current_value = []
        
        for line in text.split("\n"):
            if not line.strip():
                continue
                
            # Check if this is a continuation line (starts with whitespace)
            if line and line[0] in (' ', '\t') and current_key:
                current_value.append(line.strip())
                continue
            
            # Save previous key-value pair
            if current_key is not None:
                value = "\n".join(current_value).strip()
                self._set_toon_value(data, current_key, value)
            
            # Parse new key: value
            if ":" in line:
                key, _, value = line.partition(":")
                current_key = key.strip()
                current_value = [value.strip()] if value.strip() else []
            else:
                current_key = None
                current_value = []
        
        # Don't forget the last key-value pair
        if current_key is not None:
            value = "\n".join(current_value).strip()
            self._set_toon_value(data, current_key, value)
        
        return data

    def _parse_bracket_list(self, value: str) -> list[str] | None:
        """Parse a bracket-enclosed list: [item1, item2, item3].
        
        Handles nested brackets/parens for tool calls like:
        [tool_a({"x": 1}), tool_b({"y": 2})]
        """
        value = value.strip()
        if not (value.startswith('[') and value.endswith(']')):
            return None
        
        inner = value[1:-1].strip()
        if not inner:
            return []
        
        # Split by comma, tracking bracket depth for nested content
        items = []
        current = []
        depth = 0
        
        for char in inner:
            if char in '({[':
                depth += 1
                current.append(char)
            elif char in ')}]':
                depth -= 1
                current.append(char)
            elif char == ',' and depth == 0:
                items.append(''.join(current).strip())
                current = []
            else:
                current.append(char)
        
        if current:
            items.append(''.join(current).strip())
        
        return items

    def _set_toon_value(self, data: dict, key: str, value: str):
        """Set a value in data dict, handling bracket lists and legacy notation."""
        # Check for bracket list notation: [item1, item2]
        bracket_list = self._parse_bracket_list(value)
        if bracket_list is not None:
            data[key] = bracket_list
            return
        
        # Check for legacy indexed notation: key[idx]
        match = re.match(r'^(\w+)\[(\d+)\]$', key)
        if match:
            base_key = match.group(1)
            idx = int(match.group(2))
            if base_key not in data:
                data[base_key] = []
            while len(data[base_key]) <= idx:
                data[base_key].append("")
            data[base_key][idx] = value
        else:
            data[key] = value

    @classmethod
    def from_raw(cls, raw: Any) -> "BaseResponse":
        """Parse raw model output into a response object.
        
        This method is fully generic - subclasses do NOT need to override.
        It attempts JSON parsing first, then TOON parsing, then falls back
        to constructing a minimal response with the raw text in 'response' field.
        """
        if isinstance(raw, cls):
            return raw

        if isinstance(raw, dict):
            return cls.model_validate(raw)

        if not isinstance(raw, str):
            raw = str(raw)

        instance = cls.model_construct()

        # Try JSON parsing first
        try:
            json_str = instance._extract_json_object(raw)
            data = json.loads(json_str)
            # Verify the JSON has at least one expected field before validating
            expected_fields = set(cls.model_fields.keys())
            if expected_fields & set(data.keys()):
                return cls.model_validate(data)
        except (ValueError, json.JSONDecodeError):
            pass
        except Exception:
            # Catch Pydantic ValidationError and other errors
            pass

        # Try TOON parsing
        try:
            data = instance._parse_toon(raw)
            if data:  # Only use if we got some data
                return cls.model_validate(data)
        except Exception:
            pass

        # Fallback: construct with defaults, setting 'response' if it exists
        fallback_data = {"response": raw.strip()} if "response" in cls.model_fields else {}
        return cls.model_construct(**fallback_data)


class ReActResponse(BaseResponse):
    """Observe-Plan-Act response model for structured agent reasoning.

    This model enforces a disciplined reasoning loop:
    1. OBSERVE - Analyze current state, context, and tool results
    2. PLAN - Formulate step-by-step strategy to achieve the goal
    3. ACT - Execute via tool call or provide final answer

    Only 'action' and 'response' are preserved in conversation history;
    'observation' and 'plan' are discarded after each turn to reduce context size.
    """

    observation: str = Field(
        default="",
        description="What do I see? Analyze the current context, previous tool results, and conversation state. Identify key facts and constraints."
    )
    plan: list[str] = Field(
        default_factory=list,
        description="What is my strategy? List 2-5 concrete reasoning steps to achieve the goal. Each step should be actionable and specific."
    )
    action: Literal["tool", "answer"] = Field(
        default="answer",
        description="What type of response? Use 'tool' to invoke a tool, or 'answer' to provide the final response to the user."
    )
    response: str | list[str] = Field(
        default="",
        description="The output. If action='tool': tool invocation(s) - use a list for parallel execution. If action='answer': the complete response to the user."
    )


class Message(BaseModel):
    """A single message in the conversation history, uniform across the app."""
    role: Literal["system", "user", "assistant"]
    content: str
