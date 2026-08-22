"""GLM API 稳定性探针：连续 N 次调用，统计延迟分布与错误码（定位"不稳定"用数据说话）。

用法（在 backend/ 下）：
    python -m scripts.probe_glm --calls 20 --model glm-4.6v-flashx [--image path.jpg]
    python -m scripts.probe_glm --calls 10 --model glm-4.6v --concurrency 3

输出：p50 / p90 / p99 延迟、成功数、失败数、错误码分布（1305/429/1113/1301 等）。
建议：分别在不同时段（白天/晚上/深夜）各跑一轮，对比高峰期与闲时。
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import time

from PIL import Image
import io

from app.config import settings
from app.llm.factory import create_provider


def _tiny_image() -> bytes:
    """64×48 小图（视觉调用，模拟真实分析的最小输入）。"""
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (120, 130, 140)).save(buf, format="JPEG")
    return buf.getvalue()


async def probe_once(provider, image: bytes, model: str) -> dict:
    t0 = time.monotonic()
    try:
        await provider.analyze_image(image, "描述这张图片：天空/地面/建筑。只回答两个字。")
        return {"ok": True, "elapsed": time.monotonic() - t0, "err": ""}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "elapsed": time.monotonic() - t0, "err": f"{type(e).__name__}: {e}"[:120]}


async def run(calls: int, model: str, concurrency: int, image_path: str | None) -> None:
    provider = create_provider(model=model)
    image = open(image_path, "rb").read() if image_path else _tiny_image()
    print(f"模型: {model} | 调用次数: {calls} | 并发: {concurrency} | 图: {'自定义' if image_path else '64×48 小图'}")
    print(f"平台: {settings.llm_base_url or '默认'} | 开始时间: {time.strftime('%H:%M:%S')}\n")

    t0 = time.monotonic()
    ok_times: list[float] = []
    errs: list[str] = []
    sem = asyncio.Semaphore(concurrency)

    async def one():
        async with sem:
            r = await probe_once(provider, image, model)
        if r["ok"]:
            ok_times.append(r["elapsed"])
        else:
            errs.append(r["err"])
        return r

    results = await asyncio.gather(*[one() for _ in range(calls)])
    wall = time.monotonic() - t0

    ok = sum(1 for r in results if r["ok"])
    fail = calls - ok
    print(f"完成 {calls} 次，总耗时 {wall:.0f}s，成功 {ok}，失败 {fail}（失败率 {fail / calls * 100:.0f}%）")
    if ok_times:
        s = sorted(ok_times)
        print(f"延迟（仅成功）: p50={statistics.median(s):.1f}s  p90={s[min(len(s)-1, int(len(s)*0.9))]:.1f}s  "
              f"p99={s[min(len(s)-1, int(len(s)*0.99))]:.1f}s  max={s[-1]:.1f}s")
        print(f"平均: {statistics.mean(s):.1f}s")
    if errs:
        # 错误码归类
        from collections import Counter
        codes = Counter()
        for e in errs:
            if "1113" in e or "余额" in e:
                codes["1113 余额不足"] += 1
            elif "1305" in e:
                codes["1305 并发超限"] += 1
            elif "1301" in e:
                codes["1301 内容审核"] += 1
            elif "429" in e or "RateLimit" in e:
                codes["429 限流"] += 1
            elif "timed out" in e.lower() or "Timeout" in e:
                codes["超时"] += 1
            else:
                codes[e[:40]] += 1
        print("错误分布:", dict(codes))
        for e in errs[:5]:
            print("  样例:", e)

    print("\n结论参考：p90 若长期 >15s → 平台高峰期排队；失败率 >10% → 检查余额/并发/网络。")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="GLM API 稳定性探针")
    p.add_argument("--calls", type=int, default=20)
    p.add_argument("--model", default="glm-4.6v-flashx")
    p.add_argument("--concurrency", type=int, default=2)
    p.add_argument("--image", default=None, help="自定义测试图路径")
    args = p.parse_args()
    asyncio.run(run(args.calls, args.model, args.concurrency, args.image))
