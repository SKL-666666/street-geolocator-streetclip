"""智谱 API 压力诊断：用工具的真实调用模式连打，统计错误码/延迟分布。

用法：python scripts/diag_zhipu.py [n]
输出：每次调用（模型/状态/错误码/延迟）+ 汇总（p50/p90/p95/错误分类）。
"""
from __future__ import annotations

import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from app.config import settings  # noqa: E402
from app.llm.factory import create_provider  # noqa: E402
from app.llm.prompts import CLUE_EXTRACTION_PROMPT  # noqa: E402

IMAGES = [
    "data/eval_kartaview/Paris_2.jpg",
    "data/eval_kartaview/Rome_2.jpg",
    "data/eval_kartaview/Madrid_1.jpg",
    "data/eval_kartaview/Vienna_6.jpg",
    "data/eval_kartaview/Paris_8.jpg",
]


async def call_once(provider, image: bytes, prompt: str) -> dict:
    t0 = time.time()
    try:
        r = await asyncio.wait_for(
            provider.analyze_image(image, prompt, mime="image/jpeg"), timeout=30)
        dt = time.time() - t0
        return {"status": "ok", "ms": int(dt * 1000),
                "usage": r.usage.get("total_tokens", r.usage)}
    except asyncio.TimeoutError:
        return {"status": "timeout", "ms": int((time.time() - t0) * 1000), "usage": 0}
    except Exception as e:  # noqa: BLE001
        body = ""
        if hasattr(e, "body"):
            body = str(e.body)[:200]
        code = ""
        if hasattr(e, "status_code"):
            code = str(getattr(e, "status_code"))
        elif hasattr(e, "response") and getattr(e.response, "status_code", None):
            code = str(e.response.status_code)
        return {"status": f"err:{type(e).__name__}", "code": code,
                "body": body, "ms": int((time.time() - t0) * 1000), "usage": 0}


async def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    data = {p: Path(p).read_bytes() for p in IMAGES}
    all_results = {}

    for label, model, thinking_off in [
        ("glm-4v-flash（平衡主力）", "glm-4v-flash", False),
        ("glm-4.6v（深度/兜底）", "glm-4.6v", True),
    ]:
        print(f"── {label} 连打 {n} 次（真实图片+真实 Prompt，并发 3 模拟工具）──", flush=True)
        settings.llm_disable_thinking = thinking_off
        provider = create_provider(model=model)
        rows = []
        sem = asyncio.Semaphore(3)  # 与工具并发设置一致

        async def one(i):
            async with sem:
                img = data[f"data/eval_kartaview/{['Paris_2','Rome_2','Madrid_1','Vienna_6','Paris_8'][i % 5]}.jpg"]
                r = await call_once(provider, img, CLUE_EXTRACTION_PROMPT)
                mark = "!"
                if r["status"] == "ok":
                    mark = "."
                elif r["status"] == "timeout":
                    mark = "T"
                else:
                    mark = "E"
                print(f"  [{i+1:2d}] {mark} {r['ms']/1000:5.1f}s {r.get('code','')} {r.get('body','')[:80]}", flush=True)
                return r

        rows = await asyncio.gather(*[one(i) for i in range(n)])
        ok = [r for r in rows if r["status"] == "ok"]
        ms = sorted(r["ms"] for r in rows)
        errs = {}
        for r in rows:
            if r["status"] != "ok":
                key = r["status"] + (f"#{r.get('code','')}" if r.get("code") else "")
                errs[key] = errs.get(key, 0) + 1
        summary = {
            "n": n, "ok": len(ok),
            "timeout": sum(1 for r in rows if r["status"] == "timeout"),
            "errors": errs,
            "p50_ms": ms[len(ms) // 2] if ms else 0,
            "p90_ms": ms[int(len(ms) * 0.9)] if ms else 0,
            "p95_ms": ms[min(len(ms) - 1, int(len(ms) * 0.95))] if ms else 0,
            "max_ms": ms[-1] if ms else 0,
            "usage_avg": int(sum(r.get("usage") or 0 for r in ok) / len(ok)) if ok else 0,
        }
        print(f"  → 成功{summary['ok']}/{n} 超时{summary['timeout']} 错误{summary['errors']} "
              f"延迟p50={summary['p50_ms']/1000:.1f}s p90={summary['p90_ms']/1000:.1f}s "
              f"p95={summary['p95_ms']/1000:.1f}s 最慢{summary['max_ms']/1000:.1f}s 均token={summary['usage_avg']}", flush=True)
        all_results[label] = summary

    out = REPO / "data" / "diag_zhipu.json"
    out.write_text(json.dumps(all_results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n报告：{out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
