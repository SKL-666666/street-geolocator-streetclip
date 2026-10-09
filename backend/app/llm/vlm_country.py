"""国家级云端 VLM 复核（Step8）。

低置信(StreetCLIP margin < 阈值)时调用, 高置信直接信 StreetCLIP 省 API。
默认小米 MiMo-v2.6-flash(OpenAI兼容, nothinking), 实测国家级 70.8%。
返回 VLM 判断的国家英文名, 或 None(失败/超时 → 上层保持 StreetCLIP 结果)。
"""
from __future__ import annotations

import asyncio

from ..config import settings

# 只要求输出国家, 极简 prompt 降低 token 与跑偏
_COUNTRY_PROMPT = (
    "这张街景照片拍摄于哪个国家? 只输出国家英文名, 不要有任何其他文字、标点或解释。"
)


def _create_vlm():
    """构造 VLM provider (OpenAI 兼容)。Key 缺失 → 返回 None(降级本地)。"""
    if not settings.vlm_api_key:
        return None
    try:
        from openai import AsyncOpenAI
    except ImportError:
        return None
    kwargs: dict = {
        "api_key": settings.vlm_api_key,
        "timeout": settings.vlm_timeout_sec,
        "max_retries": 1,
    }
    if settings.vlm_base_url:
        kwargs["base_url"] = settings.vlm_base_url
    return AsyncOpenAI(**kwargs)


def _parse_country(text: str) -> str | None:
    """从 VLM 自由输出里提取国家英文名(取最后一行非空, 去标点)。"""
    if not text:
        return None
    line = text.strip().split("\n")[-1].strip()
    # 去常见包裹符号
    line = line.strip(" .。,，:：;；\"'`“”‘’()（）[]【】")
    if not line or len(line) > 60:
        return None
    return line


async def vlm_recheck_country(image_bytes: bytes) -> str | None:
    """图 → VLM 判国家英文名; 任何失败返回 None(上层回退 StreetCLIP)。"""
    client = _create_vlm()
    if client is None:
        return None
    import base64
    b64 = base64.b64encode(image_bytes).decode()
    payload: dict = {
        "model": settings.vlm_model,
        "max_tokens": 150 if settings.vlm_nothinking else 500,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": _COUNTRY_PROMPT},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ],
        }],
    }
    if settings.vlm_nothinking:
        # 小米 MiMo 关闭思考链: 非标参数, openai SDK 用 extra_body 透传
        # (实测 enable_thinking:false → reasoning_tokens 降到 2)
        payload["extra_body"] = {"enable_thinking": False}
    try:
        resp = await asyncio.wait_for(
            client.chat.completions.create(**payload),
            timeout=settings.vlm_timeout_sec + 5)
        content = resp.choices[0].message.content or ""
        return _parse_country(content)
    except Exception:  # noqa: BLE001 任何失败 → 降级本地
        return None
