"""一次性验证：智谱隐式上下文缓存是否命中我们的固定提示词（不改生产代码）。

模拟真实请求：messages = [user content=[固定文本提示词, 不同图片]]。
若第二次请求 usage.prompt_tokens_details.cached_tokens > 0 → 缓存命中 → 文本部分 token 打折。
"""
from __future__ import annotations

import asyncio
import base64
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.config import settings  # noqa: E402
from app.llm.prompts import build_clue_prompt  # noqa: E402

PROMPT = build_clue_prompt("world")


def _img_data(path: Path) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode()


async def main() -> None:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.llm_api_key,
                         base_url=settings.llm_base_url or None, timeout=120, max_retries=0)
    d = BACKEND / "data" / "eval_kartaview"
    imgs = [d / "Vienna_1.jpg", d / "Madrid_1.jpg", d / "Paris_1.jpg", d / "Rome_1.jpg"]
    for i, name in enumerate(imgs):
        resp = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {"url": _img_data(name)}},
            ]}],
            temperature=0.2,
        )
        u = resp.usage
        cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0)
        print(f"第{i+1}次 ({name.name}): prompt={u.prompt_tokens} completion={u.completion_tokens} "
              f"cached_tokens={cached}")


if __name__ == "__main__":
    asyncio.run(main())
