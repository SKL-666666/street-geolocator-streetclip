"""OpenAI 兼容供应商：OpenAI / DeepSeek / 通义(DashScope兼容模式) / 智谱GLM / 豆包 / Moonshot 等。

统一用 openai SDK + base_url 指向各家端点；图像以 data URL 形式内联。
"""
from __future__ import annotations

import asyncio
import base64

from .base import BalanceError, ContentFilterError, LLMProvider, LLMResult, OverloadError

# 全局 LLM 请求并发信号量：限制所有模式/任务的总请求并发 ≤2（平台并发上限 3，
# 留 1 余量）。修复"2 任务 × cn 双采样 = 4 请求"超限排队导致的超时潮。
_REQ_SEM = asyncio.Semaphore(2)


class OpenAICompatProvider(LLMProvider):
    name = "openai"
    # 默认模型：本应用云端统一用智谱 GLM-4.6V-FlashX（未配置 Key/模型时显示此值，
    # 而非 OpenAI 的 gpt-4o-mini——避免误导用户）
    default_model = "glm-4.6v-flashx"

    def __init__(self, api_key: str, model: str = "", base_url: str = "", timeout_sec: float = 120.0,
                 disable_thinking: bool = False):
        super().__init__(api_key, model, base_url, timeout_sec)
        self.disable_thinking = disable_thinking
        # 允许空 key 构造（未配置时进入"待配置"状态，analyze 时给出清晰错误）
        self._client = None
        if not self.api_key:
            return
        try:
            from openai import AsyncOpenAI
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("缺少 openai SDK，请先 pip install openai") from e
        kwargs: dict = {"api_key": self.api_key, "timeout": self.timeout_sec,
                        "max_retries": 1}  # 重试 2→1：429/余额不足快速失败走降级链，省无谓等待
        if self.base_url:
            kwargs["base_url"] = self.base_url
        self._client = AsyncOpenAI(**kwargs)

    async def analyze_image(self, image_bytes: bytes, prompt: str, mime: str = "image/jpeg") -> LLMResult:
        if self._client is None:
            raise RuntimeError("未配置 LLM API Key：请先在设置页填写自己的 API Key 后再分析")
        b64 = base64.b64encode(image_bytes).decode("ascii")
        kwargs: dict = {}
        # 智谱 GLM-4.6 系：关闭推理链可把耗时从 ~40s 压到数秒（速度优先）
        if self.disable_thinking:
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        try:
            # 全局限流（防并发超平台限制；信号量等待不计入超时预算，但排队时间极短）
            async with _REQ_SEM:
                resp = await self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                            ],
                        }
                    ],
                    temperature=0.2,
                    **kwargs,
                )
        except Exception as e:
            # 内容审核拦截（智谱 1301 / contentFilter）→ 转成可降级的专用异常
            if _is_content_filter_error(e):
                raise ContentFilterError() from e
            # 余额不足（智谱 1113）→ 非瞬态，明确提示（重试无意义）
            if _is_balance_error(e):
                raise BalanceError() from e
            # 平台繁忙/限流/网络抖动（1305 / 429 / 连接超时）→ 转成瞬态异常，
            # 调用方降级而非让任务失败（用户要求：无论如何必须输出结果）
            if _is_overload_error(e):
                raise OverloadError() from e
            raise
        text = resp.choices[0].message.content or ""
        usage = dict(resp.usage) if resp.usage else {}
        return LLMResult(content=text, usage=usage)

    async def complete_text(self, prompt: str, model: str | None = None) -> LLMResult:
        """纯文本补全（无图）：供离线批量生成使用（如城市档案），走同一 key/限流。"""
        if self._client is None:
            raise RuntimeError("未配置 LLM API Key：请先在设置页填写自己的 API Key")
        try:
            async with _REQ_SEM:
                resp = await self._client.chat.completions.create(
                    model=model or self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                )
        except Exception as e:
            if _is_content_filter_error(e):
                raise ContentFilterError() from e
            if _is_balance_error(e):
                raise BalanceError() from e
            if _is_overload_error(e):
                raise OverloadError() from e
            raise
        text = resp.choices[0].message.content or ""
        usage = dict(resp.usage) if resp.usage else {}
        return LLMResult(content=text, usage=usage)


def _is_content_filter_error(e: Exception) -> bool:
    """识别平台内容审核拦截错误（各家格式不同，宽匹配）。"""
    body = ""
    if hasattr(e, "body") and e.body:
        body = str(e.body)
    elif hasattr(e, "response") and e.response is not None:
        body = str(getattr(e.response, "text", ""))
    msg = str(e)
    return any(k in body or k in msg for k in (
        "contentFilter", "content_filter", "1301", "敏感内容", "不安全", "sensitive"))


def _is_overload_error(e: Exception) -> bool:
    """识别平台繁忙/限流/网络瞬态错误（智谱 1305、HTTP 429、连接/读超时等）。"""
    cls = type(e).__name__
    if cls in ("RateLimitError", "APIConnectionError", "APITimeoutError",
               "InternalServerError", "ConnectError", "ReadTimeout",
               "ConnectTimeout", "TimeoutError"):
        return True
    body = ""
    if hasattr(e, "body") and e.body:
        body = str(e.body)
    elif hasattr(e, "response") and e.response is not None:
        body = str(getattr(e.response, "text", ""))
    msg = str(e)
    return any(k in body or k in msg for k in (
        "1305", "429", "rate_limit", "rate limit", "too many requests",
        "overloaded", "overload", "busy", "繁忙", "过载", "限流",
        "并发超限", "服务器繁忙", "服务繁忙", "负载"))


def _is_balance_error(e: Exception) -> bool:
    """识别账号余额不足/资源包耗尽（智谱 1113）。"""
    body = ""
    if hasattr(e, "body") and e.body:
        body = str(e.body)
    elif hasattr(e, "response") and e.response is not None:
        body = str(getattr(e.response, "text", ""))
    msg = str(e)
    return any(k in body or k in msg for k in (
        "1113", "余额不足", "资源包", "insufficient", "无可用资源"))
