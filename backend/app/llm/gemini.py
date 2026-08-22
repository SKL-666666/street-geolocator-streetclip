"""Google Gemini 供应商（google-genai SDK，图片 inline_data 传入）。"""
from __future__ import annotations

from .base import LLMProvider, LLMResult


class GeminiProvider(LLMProvider):
    name = "gemini"
    default_model = "gemini-2.0-flash"

    def __init__(self, api_key: str, model: str = "", base_url: str = "", timeout_sec: float = 120.0):
        super().__init__(api_key, model, base_url, timeout_sec)
        if not self.api_key:
            raise ValueError("LLM_PROVIDER=gemini 需要设置 LLM_API_KEY")
        try:
            from google import genai
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("缺少 google-genai SDK，请先 pip install google-genai") from e
        self._client = genai.Client(api_key=self.api_key)

    async def analyze_image(self, image_bytes: bytes, prompt: str, mime: str = "image/jpeg") -> LLMResult:
        from google.genai import types

        resp = await self._client.aio.models.generate_content(
            model=self.model,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime),
                types.Part.from_text(text=prompt),
            ],
            config=types.GenerateContentConfig(temperature=0.2, max_output_tokens=2000),
        )
        text = resp.text or ""
        usage = {}
        if resp.usage_metadata:
            usage = {
                "prompt_tokens": resp.usage_metadata.prompt_token_count,
                "completion_tokens": resp.usage_metadata.candidates_token_count,
            }
        return LLMResult(content=text, usage=usage)
