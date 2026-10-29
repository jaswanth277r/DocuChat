from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import AsyncIterator

import httpx

from ..config import get_settings

log = logging.getLogger("docuchat.llm")


class ProviderError(Exception):
    pass


class LLMProvider(ABC):
    name = "base"
    model = ""

    @abstractmethod
    async def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        ...

    async def complete(self, messages: list[dict], max_tokens: int | None = None) -> str:
        parts: list[str] = []
        async for token in self.stream(messages):
            parts.append(token)
        return "".join(parts)

    def status(self) -> dict:
        return {"provider": self.name, "model": self.model, "mode": "cloud" if self.name != "ollama" else "local"}


class OpenAICompatibleProvider(LLMProvider):
    """OpenAI-compatible chat completions (OpenAI, Groq, vLLM, LM Studio, ...)."""

    name = "openai-compatible"

    def __init__(self, base_url: str, api_key: str, model: str, temperature: float, max_tokens: int):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    @property
    def _url(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"

    async def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": True,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        timeout = httpx.Timeout(get_settings().llm_timeout_s, connect=10.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", self._url, json=payload, headers=headers) as response:
                    if response.status_code >= 400:
                        detail = (await response.aread()).decode("utf-8", "ignore")[:500]
                        raise ProviderError(f"Provider returned HTTP {response.status_code}: {detail}")
                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            parsed = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        choice = (parsed.get("choices") or [{}])[0]
                        delta = choice.get("delta") or {}
                        content = delta.get("content")
                        if content:
                            yield content
        except httpx.HTTPError as exc:
            raise ProviderError(f"LLM request failed: {exc}") from exc

    def status(self) -> dict:
        host = self.base_url.split("//")[-1].split("/")[0]
        return {"provider": self.name, "model": self.model, "mode": "cloud", "endpoint": host}


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, base_url: str, model: str, temperature: float):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature

    async def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "options": {"temperature": self.temperature},
        }
        timeout = httpx.Timeout(get_settings().llm_timeout_s, connect=5.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", f"{self.base_url}/api/chat", json=payload) as response:
                    if response.status_code >= 400:
                        detail = (await response.aread()).decode("utf-8", "ignore")[:500]
                        raise ProviderError(f"Ollama returned HTTP {response.status_code}: {detail}")
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            parsed = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if parsed.get("error"):
                            raise ProviderError(str(parsed["error"]))
                        content = (parsed.get("message") or {}).get("content")
                        if content:
                            yield content
                        if parsed.get("done"):
                            break
        except httpx.HTTPError as exc:
            raise ProviderError(f"Ollama request failed: {exc}") from exc

    def status(self) -> dict:
        return {"provider": "ollama", "model": self.model, "mode": "local", "endpoint": self.base_url}


def get_provider() -> LLMProvider | None:
    settings = get_settings()
    provider = settings.llm_provider.lower()
    if provider in {"openai", "groq", "openai-compatible"}:
        if not settings.llm_api_key:
            return None
        return OpenAICompatibleProvider(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )
    if provider == "ollama":
        return OllamaProvider(
            base_url=settings.llm_base_url or "http://127.0.0.1:11434",
            model=settings.llm_model,
            temperature=settings.llm_temperature,
        )
    return None


def provider_status() -> dict:
    settings = get_settings()
    provider = get_provider()
    if provider:
        return {**provider.status(), "configured": True}
    if settings.llm_provider == "extractive":
        return {
            "provider": "extractive",
            "model": "grounded-extractive-v1",
            "mode": "offline",
            "configured": True,
            "note": "Answers are composed from retrieved sentences. Configure an LLM for generative answers.",
        }
    return {
        "provider": settings.llm_provider,
        "model": settings.llm_model,
        "mode": "unconfigured",
        "configured": False,
        "note": "No API key configured; generation falls back to grounded extractive answers.",
    }
