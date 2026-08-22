"""Anthropic Claude 供应商（图片以 base64 block 传入）。"""
from __future__ import annotations

import base64

from .base import LLMProvider, LLMResult


class AnthropicProvider(LLMProvider):
    name = "anthropic"
    default_model = "claude-sonnet-4-20250514"

    def __init__(self, api_key: str, model: str = "", base_url: str = "", timeout_sec: float = 120.0):
        super().__init__(api_key, model, base_url, timeout_sec)
        if not self.api_key:
            raise ValueError("LLM_PROVIDER=anthropic 需要设置 LLM_API_KEY")
        try:
            import anthropic
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("缺少 anthropic SDK，请先 pip install anthropic") from e
        self._client = anthropic.AsyncAnthropic(api_key=self.api_key, timeout=timeout_sec)

    async def analyze_image(self, image_bytes: bytes, prompt: str, mime: str = "image/jpeg") -> LLMResult:
        media_type = mime if mime in ("image/jpeg", "image/png", "image/webp", "image/gif") else "image/jpeg"
        resp = await self._client.messages.create(
            model=self.model,
            max_tokens=2000,
            temperature=0.2,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": base64.b64encode(image_bytes).decode("ascii"),
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
        usage = dict(resp.usage) if resp.usage else {}
        return LLMResult(content="".join(parts), usage=usage)
