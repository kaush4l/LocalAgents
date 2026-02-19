"""
LLM inference — Pydantic object initialized from model_id.

Architecture:
    BaseInference    — shared normalization + invoke pipeline
    OpenAIInference  — OpenAI Responses API client (serves all OpenAI-compatible providers)
    get_implementation(model_id) — canonical factory (cached per provider/model)
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from typing import Any

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, PrivateAttr

from .responses import BaseResponse

_DEFAULT_MODEL_ID = "lms/qwen/qwen3-vl-30b"
_DEFAULT_LMS_URL = "http://127.0.0.1:1234/v1"

logger = logging.getLogger(__name__)


def _first_non_empty(*values: str | None) -> str | None:
    for value in values:
        if value and value.strip():
            return value.strip()
    return None


def _provider_settings(provider: str) -> tuple[str | None, str | None]:
    key = provider.strip().lower().replace("-", "_")
    env = key.upper()

    base_url: str | None = None
    api_key: str | None = None

    if key == "openai":
        api_key = _first_non_empty(os.getenv("OPENAI_API_KEY"), os.getenv("OPENAI_API_KEY"))
    elif key in {"lms", "lmstudio", "lm_studio"}:
        base_url = _first_non_empty(os.getenv("LMS_PROVIDER_URL", _DEFAULT_LMS_URL), os.getenv("LMS_BASE_URL"))
        api_key = _first_non_empty(os.getenv("LMS_API_KEY"), os.getenv("LM_STUDIO_API_KEY"), "lm-studio")

    base_url = _first_non_empty(os.getenv(f"{env}_BASE_URL"), os.getenv(f"{env}_PROVIDER_URL"), base_url)
    api_key = _first_non_empty(os.getenv(f"{env}_API_KEY"), api_key)
    if key != "openai" and not api_key:
        api_key = key
    return base_url, api_key


class BaseInference(BaseModel):
    """Base inference model with shared normalization + invoke flow."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    provider: str
    model: str
    base_url: str | None = None
    api_key: str | None = None
    temperature: float = 0.7
    max_output_tokens: int = 32_000

    @staticmethod
    def normalize_model_identifier(model_id: str | None) -> tuple[str, str]:
        raw = (model_id or os.getenv("MODEL_ID", _DEFAULT_MODEL_ID)).strip()
        if "/" in raw:
            provider, model = raw.split("/", 1)
            return provider.strip().lower(), model.strip()
        return "openai", raw

    @staticmethod
    def _looks_like_base64(value: str) -> bool:
        if not value or len(value) < 32:
            return False
        if any(ch.isspace() for ch in value[:64]):
            return False
        allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=")
        return all(ch in allowed for ch in value[:128])

    @staticmethod
    def _file_to_data_url(path: str, mime_type: str = "image/png") -> str | None:
        try:
            if not path or not os.path.exists(path):
                return None
            with open(path, "rb") as f:
                encoded = base64.b64encode(f.read()).decode("ascii")
            return f"data:{mime_type};base64,{encoded}"
        except Exception:
            return None

    @staticmethod
    def _normalize_multimodal(multimodal: Any) -> list[dict]:
        if not multimodal:
            return []
        items = multimodal if isinstance(multimodal, list) else [multimodal]
        normalized: list[dict] = []
        for item in items:
            if item is None:
                continue
            if isinstance(item, dict):
                normalized.append(item)
            elif hasattr(item, "model_dump"):
                try:
                    normalized.append(item.model_dump())
                except Exception:
                    pass
            else:
                modality_type = getattr(item, "modality_type", None)
                collection = getattr(item, "collection", None)
                if modality_type is not None:
                    normalized.append({"modality_type": modality_type, "collection": collection or []})
        return normalized

    def normalize(self, prompt: str, multimodal: Any = None) -> list[dict]:
        content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]

        for entry in self._normalize_multimodal(multimodal):
            if entry.get("modality_type") != "image":
                continue
            collection = entry.get("collection") or []
            if not isinstance(collection, list):
                collection = [collection]

            for raw in collection:
                if not isinstance(raw, str) or not raw:
                    continue
                if raw.startswith(("http://", "https://", "data:")):
                    image_url = raw
                elif file_url := self._file_to_data_url(raw):
                    image_url = file_url
                elif self._looks_like_base64(raw):
                    image_url = f"data:image/png;base64,{raw}"
                else:
                    continue
                content.append({"type": "input_image", "image_url": image_url})

        return [{"role": "user", "content": content}]

    def _infer(self, input_payload: list[dict], model: str) -> str:
        raise NotImplementedError("Subclasses must implement _infer")

    async def invoke(
        self,
        prompt: str,
        model_id: str | None = None,
        response_model: type | None = None,
        multimodal: Any = None,
    ) -> Any:
        provider, model = self.normalize_model_identifier(model_id or f"{self.provider}/{self.model}")
        if provider != self.provider:
            return await get_implementation(f"{provider}/{model}").invoke(
                prompt,
                model_id=f"{provider}/{model}",
                response_model=response_model,
                multimodal=multimodal,
            )

        input_payload = self.normalize(prompt, multimodal=multimodal)
        logger.debug("[%s] invoking model=%s prompt_chars=%d", self.provider, model, len(prompt))

        def _call() -> Any:
            text = self._infer(input_payload, model)
            logger.info("Raw model output (%d chars): %s", len(text), text[:2000])
            if response_model and isinstance(response_model, type) and issubclass(response_model, BaseResponse):
                return response_model.from_raw(text)
            return text

        return await asyncio.to_thread(_call)


class OpenAIInference(BaseInference):
    """OpenAI Responses API client for OpenAI-compatible providers."""

    _client: OpenAI = PrivateAttr()

    def model_post_init(self, __context: Any) -> None:
        kwargs: dict[str, Any] = {}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        if self.api_key:
            kwargs["api_key"] = self.api_key
        self._client = OpenAI(**kwargs)
        logger.info("OpenAIInference initialized (provider=%s, base_url=%s)", self.provider, self.base_url or "default")

    @staticmethod
    def _extract_text(response: Any) -> str:
        output_text = getattr(response, "output_text", None)
        if isinstance(output_text, str) and output_text.strip():
            return output_text

        parts: list[str] = []
        for item in getattr(response, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                text = getattr(content, "text", None)
                if isinstance(text, str):
                    parts.append(text)
                elif isinstance(text, dict) and isinstance(text.get("value"), str):
                    parts.append(text["value"])
        return "\n".join(parts).strip() if parts else str(response)

    def _infer(self, input_payload: list[dict], model: str) -> str:
        request: dict[str, Any] = {
            "model": model,
            "input": input_payload,
            "temperature": self.temperature,
        }
        if self.max_output_tokens > 0:
            request["max_output_tokens"] = self.max_output_tokens
        response = self._client.responses.create(**request)
        return self._extract_text(response)


# Backward compatibility alias
LMStudioInference = OpenAIInference

# Cache per provider/model identifier
_IMPLEMENTATIONS: dict[str, BaseInference] = {}


def get_implementation(model_id: str | None = None) -> BaseInference:
    """Canonical factory — cached per provider/model pair."""
    provider, model = BaseInference.normalize_model_identifier(model_id)
    key = f"{provider}/{model}"
    if (existing := _IMPLEMENTATIONS.get(key)) is not None:
        return existing

    base_url, api_key = _provider_settings(provider)
    impl = OpenAIInference(provider=provider, model=model, base_url=base_url, api_key=api_key)
    _IMPLEMENTATIONS[key] = impl
    return impl
