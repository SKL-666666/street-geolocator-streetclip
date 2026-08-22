"""视觉模型稳定性对比评测（多平台多模型选型用）。

用法：python scripts/stability_check.py
统计每模型：成功率 / 超时率 / JSON解析失败率 / 城市假设完整率 / 平均·最大耗时 / 国家Top1。
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from app.config import settings  # noqa: E402
from app.llm.factory import create_provider  # noqa: E402
from app.pipeline.scene import SceneAnalyzer  # noqa: E402

# 评测图（真值：国家）
IMAGES = [
    ("data/eval_kartaview/Paris_2.jpg", "France"),
    ("data/eval_kartaview/Paris_8.jpg", "France"),
    ("data/eval_kartaview/Rome_2.jpg", "Italy"),
    ("data/eval_kartaview/Rome_5.jpg", "Italy"),
    ("data/eval_kartaview/Madrid_1.jpg", "Spain"),
    ("data/eval_kartaview/Madrid_6.jpg", "Spain"),
]

# 候选模型配置：(标签, provider名, model, 关思考, 单图限时s)
CONFIGS = [
    ("GLM-4v-flash(现主力)", "openai", "glm-4v-flash", False, 20),
    ("GLM-4.6v-FlashX(候选)", "openai", "glm-4.6v-flashx", False, 25),
    ("GLM-4.6v(关思考)", "openai", "glm-4.6v", True, 25),
    # 拿到其他平台 key 后在此追加，例如：
    # ("Qwen-VL-Max", "openai", "qwen-vl-max", False, 20),     # 通义（base_url 指向 dashscope）
    # ("Doubao-vision", "openai", "doubao-1.5-vision-pro-32k", False, 20),  # 豆包
    # ("ERNIE-4.5-VL", "openai", "ernie-4.5-vl-8b", False, 20),  # 百度千帆
]


def country_ok(hypotheses, truth: str) -> bool:
    from app.geokb.engine import _canonical_country
    return bool(hypotheses) and _canonical_country(hypotheses[0].country) == truth


async def run_one(provider, model_cfg: dict, image: bytes, timeout: float) -> dict:
    settings.llm_disable_thinking = model_cfg["thinking_off"]
    analyzer = SceneAnalyzer(provider, retries=0, samples=1,
                             primary_timeout=timeout, fallback_provider=None)
    t0 = time.time()
    try:
        scene = await asyncio.wait_for(analyzer.analyze(image), timeout=timeout + 2)
        dt = time.time() - t0
        return {"status": "ok", "ms": int(dt * 1000), "scene": scene}
    except asyncio.TimeoutError:
        return {"status": "timeout", "ms": int((time.time() - t0) * 1000), "scene": None}
    except Exception as e:  # noqa: BLE001
        return {"status": f"err:{type(e).__name__}", "ms": int((time.time() - t0) * 1000), "scene": None}


async def main() -> int:
    results = {}
    for label, pname, model, thinking_off, timeout in CONFIGS:
        print(f"── {label}（{model}）──", flush=True)
        rows = []
        try:
            settings.llm_provider = pname
            provider = create_provider(model=model)
        except Exception as e:  # noqa: BLE001
            print(f"  初始化失败：{e}")
            continue
        for fpath, truth in IMAGES:
            data = Path(fpath).read_bytes()
            r = await run_one(provider, {"thinking_off": thinking_off}, data, timeout)
            if r["status"] == "ok":
                s = r["scene"]
                cities = [(h.city, round(h.confidence, 2)) for h in s.city_hypotheses[:2]]
                rows.append({"status": "ok", "ms": r["ms"],
                             "country_ok": country_ok(s.country_hypotheses, truth),
                             "city_count": len(s.city_hypotheses),
                             "cities": cities})
                print(f"  {fpath.split('/')[-1]:16s} {r['ms']/1000:5.1f}s "
                      f"国家{'✓' if rows[-1]['country_ok'] else '✗'} 城市{rows[-1]['city_count']}个", flush=True)
            else:
                rows.append({"status": r["status"], "ms": r["ms"],
                             "country_ok": False, "city_count": 0, "cities": []})
                print(f"  {fpath.split('/')[-1]:16s} {r['ms']/1000:5.1f}s {r['status']}", flush=True)
        ok = [r for r in rows if r["status"] == "ok"]
        results[label] = {
            "n": len(rows), "ok": len(ok),
            "timeout": sum(1 for r in rows if r["status"] == "timeout"),
            "errors": sum(1 for r in rows if r["status"].startswith("err")),
            "avg_ms": int(sum(r["ms"] for r in rows) / len(rows)) if rows else 0,
            "max_ms": max((r["ms"] for r in rows), default=0),
            "country_top1": round(sum(1 for r in ok if r["country_ok"]) / len(ok), 2) if ok else 0,
            "city_full": round(sum(1 for r in ok if r["city_count"] >= 1) / len(ok), 2) if ok else 0,
        }

    print("\n===== 稳定性对比 =====")
    print(f"{'模型':<22}{'成功':>5}{'超时':>5}{'异常':>5}{'均耗时':>8}{'最慢':>7}{'国家Top1':>9}{'城市≥1':>8}")
    for label, r in results.items():
        print(f"{label:<22}{r['ok']}/{r['n']:>3}{r['timeout']:>5}{r['errors']:>5}"
              f"{r['avg_ms']/1000:>7.1f}s{r['max_ms']/1000:>6.1f}s{r['country_top1']:>9.0%}{r['city_full']:>8.0%}")
    out = REPO / "data" / "stability_report.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"报告：{out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
