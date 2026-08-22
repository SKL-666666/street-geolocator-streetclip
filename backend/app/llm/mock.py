"""Mock 提供商：离线开发/测试用，返回预设 JSON。"""
from __future__ import annotations

from .base import LLMProvider, LLMResult

MOCK_RESPONSE = """{
  "is_street_view": true,
  "scene_type": "street",
  "visible_text": ["CAFÉ CENTRAL"],
  "languages": ["Spanish"],
  "traffic_signs": ["yellow diamond warning sign"],
  "architecture": ["whitewashed walls", "flat roofs"],
  "vegetation": ["palm trees"],
  "terrain": ["coastal hills"],
  "weather": ["sunny"],
  "driving_side": "right",
  "unique_features": ["orange-tiled church tower"],
  "country_hypotheses": [{"country": "Spain", "reasoning": "Spanish text, palm trees, whitewashed architecture", "confidence": 0.72},
                         {"country": "Portugal", "reasoning": "similar coastal Mediterranean style", "confidence": 0.55}],
  "city_hypotheses": [{"city": "Málaga", "country": "Spain", "reasoning": "coastal Andalusian style", "confidence": 0.4}],
  "overall_confidence": 0.55,
  "summary": "Mock provider: Mediterranean coastal street scene with Spanish text."
}"""


class MockProvider(LLMProvider):
    name = "mock"
    default_model = "mock-v1"

    async def analyze_image(self, image_bytes: bytes, prompt: str, mime: str = "image/jpeg") -> LLMResult:
        # 模拟一个"会偶尔抽风"的模型：返回可解析的 JSON
        return LLMResult(content=MOCK_RESPONSE, usage={"mock": True})
