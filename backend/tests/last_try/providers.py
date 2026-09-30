"""
providers.py — a small, provider-agnostic LLM interface.

Every backend only needs to implement one method: `complete(system_prompt,
user_message)`. The pipeline always sends the SAME system_prompt (the big,
cached schema + one-shot instructions) on every call and a small, unique
user_message per chunk — this shape is exactly what provider-side prompt
caching is built for.

Add a new backend by subclassing LLMProvider and registering it in
build_provider() below; nothing else in the pipeline needs to change.
"""

from __future__ import annotations

import abc
import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class LLMResponse:
    text: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cached_tokens: Optional[int] = None
    model: str = ""


class LLMProvider(abc.ABC):
    """Generic provider interface. See module docstring."""

    name: str = "generic"

    def __init__(self, model: str):
        self.model = model

    @abc.abstractmethod
    def complete(
        self,
        system_prompt: str,
        user_message: str,
        *,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Send one request and return the raw text + usage/cache metadata."""
        raise NotImplementedError


class AnthropicProvider(LLMProvider):
    """
    Uses explicit `cache_control` on the system block, so the (large)
    schema/instructions prompt is cached server-side across chunk calls and
    only the small per-chunk user message is billed/processed at full
    price after the first call.
    """

    name = "anthropic"

    def __init__(self, model: str, api_key: Optional[str] = None):
        super().__init__(model)
        import anthropic  # imported lazily so the dependency is optional

        self._client = anthropic.Anthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY")
        )

    def complete(self, system_prompt, user_message, *, max_tokens=4096, temperature=0.0):
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_message}],
        )
        text = "".join(block.text for block in resp.content if block.type == "text")
        usage = resp.usage
        return LLMResponse(
            text=text,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            cached_tokens=getattr(usage, "cache_read_input_tokens", None),
            model=self.model,
        )


class OpenAICompatibleProvider(LLMProvider):
    """
    Works with the OpenAI API and with anything that speaks the same wire
    format via a custom base_url — Azure OpenAI, OpenRouter, a local vLLM
    server, Ollama's OpenAI-compatible endpoint, etc.

    These backends cache automatically server-side once a prompt prefix is
    long enough (commonly >1024 tokens) and byte-for-byte identical across
    calls — there is no client flag to set. Sending the exact same
    system_prompt on every chunk call (as this pipeline does) is all that's
    required to benefit from it.
    """

    name = "openai-compatible"

    def __init__(self, model: str, api_key: Optional[str] = None, base_url: Optional[str] = None):
        super().__init__(model)
        import openai  # imported lazily so the dependency is optional

        self._client = openai.OpenAI(
            api_key=api_key or os.environ.get("OPENAI_API_KEY", "not-needed-for-local-servers"),
            base_url=base_url or os.environ.get("OPENAI_BASE_URL"),
        )

    def complete(self, system_prompt, user_message, *, max_tokens=4096, temperature=0.0):
        resp = self._client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )
        choice = resp.choices[0]
        usage = resp.usage
        cached = None
        details = getattr(usage, "prompt_tokens_details", None)
        if details is not None:
            cached = getattr(details, "cached_tokens", None)
        return LLMResponse(
            text=choice.message.content,
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
            cached_tokens=cached,
            model=self.model,
        )


def build_provider(
    name: str,
    model: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> LLMProvider:
    """Factory: turn a --provider string into a concrete LLMProvider."""
    key = name.lower()
    if key in ("anthropic", "claude"):
        return AnthropicProvider(model=model, api_key=api_key)
    if key in ("openai", "openai-compatible", "openrouter", "azure", "local", "vllm", "ollama"):
        return OpenAICompatibleProvider(model=model, api_key=api_key, base_url=base_url)
    raise ValueError(
        f"Unknown provider '{name}'. Use 'anthropic' or 'openai-compatible' "
        "(the latter also covers OpenAI, Azure, OpenRouter, vLLM, Ollama, etc. via --base-url)."
    )