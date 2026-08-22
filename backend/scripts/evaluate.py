"""评估闭环：用带真值的街景图集批量评测管线（方案 1）。

用法（在 backend/ 下，.venv 激活）：
    python scripts/evaluate.py                  # 默认模式：LLM+KB+工具，跑全部图集
    python scripts/evaluate.py --limit 5        # 只跑前 5 张（快速冒烟）
    python scripts/evaluate.py --ablation        # 消融：llm-only / +kb / +kb+tools 三组对比
    python scripts/evaluate.py --no-tools        # 关工具（省外部调用）

输出：控制台表格 + data/eval/report.json（每次运行追加到 history）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.geokb.engine import _canonical_country, cross_filter, merge_into_scene  # noqa: E402
from app.llm.factory import create_provider  # noqa: E402
from app.pipeline.exif import extract_gps  # noqa: E402
from app.pipeline.prior_singleton import compute_prior  # noqa: E402
from app.pipeline.scene import SceneAnalyzer  # noqa: E402
from app.pipeline.tools_pass import run_fact_check, run_tools_pass  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent.parent / "data" / "eval"
META = EVAL_DIR / "metadata.json"
REPORT = EVAL_DIR / "report.json"
HISTORY = EVAL_DIR / "history.json"

# 真值：城市 → (国家, 城市)（AI_GeoDetect 集；KartaView 集从 metadata 动态生成）
GROUND_TRUTH = {
    "budapest": ("Hungary", "Budapest"),
    "kyiv": ("Ukraine", "Kyiv"),
    "warsaw": ("Poland", "Warsaw"),
    "prague": ("Czechia", "Prague"),
    "ood": (None, None),  # out-of-distribution：不参与国家/城市准确率
}

# KartaView 独立评测集：城市 → 国家
KARTAVIEW_CITIES = {
    "Paris": "France", "Berlin": "Germany", "Rome": "Italy",
    "Madrid": "Spain", "Vienna": "Austria",
}


async def analyze_one(image_path: str, use_kb: bool, use_tools: bool):
    """在进程内跑完整管线（可开关 KB/工具，做消融）。返回指标字典。"""
    data = Path(image_path).read_bytes()
    started = time.monotonic()
    llm_calls = 0
    entry = {"file": image_path}

    gps = extract_gps(data)
    if gps:
        entry.update(status="exif", level="exact",
                     lat=gps.lat, lon=gps.lon, llm_calls=0, ms=0)
        return entry

    provider = create_provider()
    analyzer = SceneAnalyzer(provider)
    scene = await analyzer.analyze(data)
    llm_calls += 1

    if not scene.is_street_view:
        entry.update(status="ok", level="none", scene_type=scene.scene_type,
                     llm_calls=llm_calls, ms=int((time.monotonic() - started) * 1000))
        return entry

    kb_rows = None
    if use_kb:
        llm_conf = {h.country: h.confidence for h in scene.country_hypotheses}
        gk = cross_filter(scene, llm_conf)
        merge_into_scene(gk, scene)
        kb_rows = gk.countries

    prior = compute_prior(data)
    prior_hit = prior is not None

    facts = []
    if use_tools:
        facts = await run_tools_pass(scene)
        if any(f.ok for f in facts):
            await run_fact_check(provider, scene, facts)
            llm_calls += 1

    top = scene.country_hypotheses[0] if scene.country_hypotheses else None
    entry.update(
        status="ok",
        level="city" if (scene.city_hypotheses and scene.city_hypotheses[0].confidence >= 0.5) else "country",
        top_country=top.country if top else None,
        top_conf=round(top.confidence, 3) if top else 0.0,
        countries=[(h.country, round(h.confidence, 3)) for h in scene.country_hypotheses[:3]],
        cities=[(h.city, round(h.confidence, 3)) for h in scene.city_hypotheses[:3]],
        kb_rows=len(kb_rows or []),
        facts_ok=sum(1 for f in facts if f.ok),
        prior=({"city": prior.city, "score": round(prior.score, 3)} if prior_hit else None),
        llm_calls=llm_calls,
        ms=int((time.monotonic() - started) * 1000),
    )
    return entry


def load_set(args_set: str) -> tuple[list[str], dict, dict]:
    """按 --set 加载图集：返回 (文件列表, 真值映射, 城市→国家)。"""
    if args_set == "kartaview":
        meta_path = Path(__file__).resolve().parent.parent / "data" / "eval_kartaview" / "metadata.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else []
        files = [m["file"] for m in meta]
        # 真值：城市 → (国家, 城市)，从 metadata 解析
        gt: dict[str, tuple] = {}
        for m in meta:
            city = m["city"]
            gt[m["file"].split("/")[-1].split("\\")[-1].split("_")[0]] = (m["country"], city)
        return files, gt, {}
    meta_path = Path(__file__).resolve().parent.parent / "data" / "eval" / "metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else []
    files = [m["file"] for m in meta]
    return files, GROUND_TRUTH, {}


def calibration(entries: list[dict], gt: dict) -> list[dict]:
    """A7：按 top_conf 分桶统计命中率（置信度校准）。"""
    bins = [(0.0, 0.3), (0.3, 0.5), (0.5, 0.7), (0.7, 1.01)]
    out = []
    for lo, hi in bins:
        group = []
        for e in entries:
            fname = e["file"].split("/")[-1].split("\\")[-1]
            city_key = fname.split("_")[0]
            if city_key not in gt or not gt[city_key][0]:
                continue
            conf = e.get("top_conf", 0)
            if lo <= conf < hi:
                group.append(e)
        if not group:
            continue
        hits = 0
        for e in group:
            fname = e["file"].split("/")[-1].split("\\")[-1]
            city_key = fname.split("_")[0]
            gt_country, _ = gt[city_key]
            if _canonical_country(e.get("top_country") or "") == gt_country:
                hits += 1
        out.append({"bin": f"{lo:.1f}~{hi:.1f}", "n": len(group),
                    "hit_rate": round(hits / len(group), 3)})
    return out


def score(entries: list[dict], gt: dict | None = None) -> dict:
    """按真值打分。gt: 文件前缀 → (国家, 城市)；缺省用内置表。"""
    gt = gt or GROUND_TRUTH
    n = n_country = n_city = n_country_hit = n_city_hit = 0
    kb_hit = kb_eligible = 0
    for e in entries:
        fname = e["file"].split("/")[-1].split("\\")[-1]
        city_key = fname.split("_")[0]
        g = gt.get(city_key)
        gt_country = g[0] if g else None
        gt_city = g[1] if g else None
        if not gt_country:
            continue
        n += 1
        n_country += 1
        top = _canonical_country(e.get("top_country") or "")
        if top == gt_country:
            n_country_hit += 1
        # 城市命中：城市假设 OR MixVPR 先验 命中真值城市
        n_city += 1
        city_hit = any(_canonical_country(c[0]) == gt_city for c in e.get("cities", []))
        prior = e.get("prior")
        if prior and _canonical_country(prior.get("city", "")) == gt_city:
            city_hit = True
        if city_hit:
            n_city_hit += 1
        if "kb_rows" in e:
            kb_eligible += 1
            if e.get("kb_rows", 0) > 0:
                kb_hit += 1
    return {
        "n": n,
        "country_top1": round(n_country_hit / n_country, 3) if n_country else 0,
        "city_any": round(n_city_hit / n_city, 3) if n_city else 0,
        "kb_covered": round(kb_hit / kb_eligible, 3) if kb_eligible else 0,
        "avg_ms": int(sum(e.get("ms", 0) for e in entries) / max(len(entries), 1)),
        "avg_llm_calls": round(sum(e.get("llm_calls", 0) for e in entries) / max(len(entries), 1), 2),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 张")
    ap.add_argument("--ablation", action="store_true", help="消融对比（3 组配置，约 3 倍 LLM 调用）")
    ap.add_argument("--no-kb", action="store_true")
    ap.add_argument("--no-tools", action="store_true")
    ap.add_argument("--set", choices=["eval", "kartaview"], default="eval",
                    help="评测集：eval=AI_GeoDetect 23 张；kartaview=独立 5 城（MixVPR 未见）")
    args = ap.parse_args()

    files, gt, _ = load_set(args.set)
    if not files:
        print(f"缺少评测图集（--set={args.set}），请先运行对应构建脚本")
        return 1
    if args.limit:
        files = files[: args.limit]
    print(f"评测图集：{len(files)} 张（{args.set}）\n")

    configs = [(True, True)]
    if args.ablation:
        configs = [(False, False), (True, False), (True, True)]

    all_reports = {}
    for use_kb, use_tools in configs:
        label = f"LLM+KB+工具" if (use_kb and use_tools) else (
            "LLM+KB" if use_kb else "纯LLM")
        print(f"── 配置：{label} ──")
        entries = asyncio.run(run_batch(files, use_kb, use_tools))
        s = score(entries, gt)
        print(f"  结果：国家Top1={s['country_top1']:.1%} 城市命中={s['city_any']:.1%} "
              f"KB覆盖={s['kb_covered']:.1%} 平均{s['avg_ms']}ms/张, LLM {s['avg_llm_calls']}次/张")
        # A7：置信度校准
        cal = calibration(entries, gt)
        if cal:
            print("  校准曲线（top_conf 分桶 → 真实命中率）：")
            for row in cal:
                print(f"    [{row['bin']}] n={row['n']:2d} 命中率={row['hit_rate']:.1%}")
        all_reports[label] = {"score": s, "entries": entries,
                              "calibration": cal, "set": args.set}

    REPORT.write_text(json.dumps(all_reports, ensure_ascii=False, indent=1), encoding="utf-8")
    history = json.loads(HISTORY.read_text(encoding="utf-8")) if HISTORY.exists() else []
    history.append({"time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "limit": args.limit, "configs": all_reports})
    HISTORY.write_text(json.dumps(history, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"报告已保存：{REPORT}（历史：{HISTORY}）")
    return 0


async def run_batch(files: list[str], use_kb: bool, use_tools: bool) -> list[dict]:
    """单事件循环跑完整批（避免反复建/关事件循环）。"""
    entries = []
    for i, f in enumerate(files, 1):
        print(f"  [{i}/{len(files)}] {f.split('/')[-1]} …", end=" ", flush=True)
        try:
            e = await analyze_one(f, use_kb, use_tools)
        except Exception as ex:  # noqa: BLE001
            e = {"file": f, "status": "error", "error": str(ex)[:120], "ms": 0, "llm_calls": 0}
            print(f"ERROR {str(ex)[:80]}")
            entries.append(e)
            continue
        entries.append(e)
        print(f"top={e.get('top_country')} ({e.get('top_conf', 0)}), {e.get('ms')}ms, "
              f"llm×{e.get('llm_calls', 0)}")
    await asyncio.sleep(0.5)  # 给 httpx 后台清理让出时间片，避免退出时报 Event loop closed
    return entries


if __name__ == "__main__":
    sys.exit(main())
