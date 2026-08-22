"""按配置创建 LLM 供应商实例。"""
from __future__ import annotations

from ..config import settings
from .base import LLMProvider
from .mock import MockProvider


def create_provider(model: str | None = None,
                    disable_thinking: bool | None = None) -> LLMProvider:
    """创建 LLM 供应商实例；model/disable_thinking 传值时覆盖配置（用于模式级差异）。"""
    provider_name = settings.llm_provider.lower()

    if provider_name == "mock":
        return MockProvider(api_key="", model=model or settings.llm_model)

    common = dict(
        api_key=settings.llm_api_key,
        model=model or settings.llm_model,
        base_url=settings.llm_base_url,
        timeout_sec=settings.llm_timeout_sec,
    )

    if provider_name == "openai":
        from .openai_compat import OpenAICompatProvider
        thinking = (settings.llm_disable_thinking
                    if disable_thinking is None else disable_thinking)
        return OpenAICompatProvider(**common, disable_thinking=thinking)

    if provider_name == "anthropic":
        from .anthropic import AnthropicProvider
        return AnthropicProvider(**common)

    if provider_name == "gemini":
        from .gemini import GeminiProvider
        return GeminiProvider(**common)

    raise ValueError(
        f"未知 LLM_PROVIDER={settings.llm_provider!r}，可选：mock | openai | anthropic | gemini。"
        "其他 OpenAI 兼容服务请用 openai + LLM_BASE_URL 指向其端点。"
    )
