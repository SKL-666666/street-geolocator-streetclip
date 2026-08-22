"""A/B 评测：知识库丰富前 vs 后，同一批图片的国家 Top1 成功率对比。

用法：
  python scripts/eval_ab.py                    # 跑默认 10 张，存 data/eval_ab_results.json
  python scripts/eval_ab.py --subset n          # 取前 n 张
  python scripts/eval_ab.py --out path.json     # 指定输出文件

A（新知识库）：后端正常启动。
B（旧知识库）：以 EVAL_LEGACY_KB=1 启动后端再跑一次，输出到不同文件，最后人工对比
（或本脚本 --out 分开保存）。判定：candidates[0].country == metadata.country（国家 Top1）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"
BACKEND = Path(__file__).resolve().parent.parent
META = BACKEND / "data" / "eval_kartaview" / "metadata.json"

# 默认 10 张：巴黎3 + 罗马2 + 马德里2 + 维也纳3（覆盖 4 城）
DEFAULT_SUBSET = [
    "Paris_1.jpg", "Paris_3.jpg", "Paris_6.jpg",
    "Rome_1.jpg", "Rome_5.jpg",
    "Madrid_1.jpg", "Madrid_3.jpg",
    "Vienna_1.jpg", "Vienna_3.jpg", "Vienna_5.jpg",
]


def _post_analyze(image_path: Path, mode: str = "balanced", scope: str = "world") -> str:
    """multipart 上传 → task_id。"""
    boundary = "----evalab" + str(int(time.time() * 1000))
    with open(image_path, "rb") as f:
        data = f.read()
    body = b""
    for name, value in (("mode", mode), ("scope", scope)):
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n"
                 f"{value}\r\n").encode()
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
             f"filename=\"{image_path.name}\"\r\nContent-Type: image/jpeg\r\n\r\n").encode()
    body += data + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"{BASE}/api/analyze", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())["task_id"]


def _get_task(task_id: str) -> dict:
    req = urllib.request.Request(f"{BASE}/api/tasks/{task_id}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())["task"]


def _wait_done(task_id: str, timeout: float = 150.0) -> dict:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        task = _get_task(task_id)
        if task["status"] in ("succeeded", "failed"):
            return task
        time.sleep(1.0)
    raise TimeoutError(f"任务 {task_id} 超时")


def _norm_country(name: str) -> str:
    """国家名归一化（中文→英文规范名）。"""
    try:
        from app.geokb.countries import COUNTRY_ALIASES
        return COUNTRY_ALIASES.get(name or "", name or "")
    except Exception:
        return name or ""


def evaluate(subset: list[str], out_path: Path) -> dict:
    meta_list = json.loads(META.read_text(encoding="utf-8"))
    by_file = {Path(m["file"]).name: m for m in meta_list}
    rows = []
    ok = 0
    degraded = 0
    for name in subset:
        meta = by_file.get(name)
        if meta is None:
            print(f"!! {name} 不在 metadata 中，跳过")
            continue
        img = Path(meta["file"])
        print(f">> {name} （{meta['country']}）上传中...")
        try:
            task_id = _post_analyze(img)
            task = _wait_done(task_id)
        except Exception as e:  # noqa: BLE001
            rows.append({"file": name, "truth": meta["country"], "error": str(e)})
            print(f"   !! 异常：{e}")
            continue
        cands = task.get("candidates") or []
        top = cands[0] if cands else {}
        top_country = _norm_country(top.get("country", ""))
        correct = top_country == meta["country"]
        if correct:
            ok += 1
        if task.get("meta", {}).get("degraded"):
            degraded += 1
        llm_top = ""
        scene = task.get("scene") or {}
        if scene.get("country_hypotheses"):
            llm_top = _norm_country(scene["country_hypotheses"][0].get("country", ""))
        rows.append({
            "file": name, "truth": meta["country"],
            "top1": top_country, "correct": correct,
            "llm_top1": llm_top,
            "city_zh": top.get("city_zh", ""),
            "score": round(float(top.get("score", 0)), 3),
            "elapsed_ms": task.get("elapsed_ms", 0),
            "degraded": bool(task.get("meta", {}).get("degraded")),
        })
        print(f"   真值={meta['country']:<10} Top1={top_country:<12} "
              f"{'✓' if correct else '✗'}  {task.get('elapsed_ms', 0)}ms"
              f"{'  [降级]' if rows[-1]['degraded'] else ''}")
        time.sleep(0.5)  # 温和节流

    summary = {
        "total": len(rows), "correct": ok,
        "accuracy_top1": round(ok / len(rows), 3) if rows else 0.0,
        "degraded": degraded,
    }
    out = {"summary": summary, "rows": rows}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n=== 结果：{ok}/{len(rows)} = {summary['accuracy_top1']:.1%}（降级 {degraded}）===")
    print(f"已保存 {out_path}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--subset", type=int, default=0, help="取前 n 张（0=默认 10 张清单）")
    ap.add_argument("--out", type=str, default=str(BACKEND / "data" / "eval_ab_results.json"))
    args = ap.parse_args()
    if args.subset:
        meta_all = json.loads(META.read_text(encoding="utf-8"))
        files = [Path(m["file"]).name for m in meta_all][: args.subset]
    else:
        files = DEFAULT_SUBSET
    evaluate(files, Path(args.out))
    sys.exit(0)
