"""供应商无关的 LLM 接口定义。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMResult:
    content: str                      # 模型返回文本
    usage: dict[str, Any] = field(default_factory=dict)


class ContentFilterError(Exception):
    """平台内容审核拦截（如智谱 1301）：输入图片或生成内容被判为敏感。

    调用方应优雅降级（本地先验/检索兜底），而不是让任务失败。
    """

    def __init__(self, message: str = "内容审核拦截：图片或生成内容被平台判定为敏感"):
        super().__init__(message)


class OverloadError(Exception):
    """平台繁忙/限流/网络抖动（如智谱 1305、HTTP 429、连接超时）。

    属瞬态故障：调用方应降级（快速模型重试或本地先验兜底），而不是让任务失败。
    """

    def __init__(self, message: str = "LLM 平台繁忙或限流（瞬态故障）"):
        super().__init__(message)


class BalanceError(OverloadError):
    """LLM 账号余额不足/资源包耗尽（如智谱 code 1113）。

    非瞬态故障：重试无意义，调用方应降级并提示用户充值/更换 Key。
    """

    def __init__(self, message: str = "LLM 账号余额不足或资源包耗尽，请充值或更换 API Key"):
        super().__init__(message)


class LLMProvider(ABC):
    """多模态 LLM 供应商抽象。

    子类实现 analyze_image：把一张图 + 提示词发给模型，
    返回文本（由调用方做健壮 JSON 解析）。
    """

    name: str = "base"
    default_model: str = ""
    supports_image: bool = True

    def __init__(self, api_key: str, model: str = "", base_url: str = "", timeout_sec: float = 120.0):
        self.api_key = api_key
        self.model = model or self.default_model
        self.base_url = base_url
        self.timeout_sec = timeout_sec

    @abstractmethod
    async def analyze_image(
        self,
        image_bytes: bytes,
        prompt: str,
        mime: str = "image/jpeg",
    ) -> LLMResult:
        """发送单图分析请求，返回模型文本输出。"""
        raise NotImplementedError

    def describe(self) -> dict:
        return {"name": self.name, "model": self.model}
