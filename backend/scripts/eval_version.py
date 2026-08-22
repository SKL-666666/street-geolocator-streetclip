"""通用评测：对指定后端端口跑一批图，输出国家 Top1 准确率。

用法：python scripts/eval_version.py --port 8011 [--dir eval_minor] [--base /abs/backend/data] [--out xx.json]
默认用 eval_minor（11 张荒野乡村图，真值=文件名）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

BASE_ROOT = Path(__file__).resolve().parent.parent / "data"


def analyze(port: int, img: Path) -> dict:
    boundary = "----ev" + str(int(time.time() * 1000))
    body = b""
    for n, v in (("mode", "balanced"), ("scope", "world")):
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{n}\"\r\n\r\n{v}\r\n").encode()
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{img.name}\"\r\n"
             "Content-Type: image/jpeg\r\n\r\n").encode()
    body += img.read_bytes() + b"\r\n" + f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/analyze", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        tid = json.loads(r.read())["task_id"]
    t0 = time.monotonic()
    while time.monotonic() - t0 < 120:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/tasks/{tid}", timeout=30) as r:
                task = json.loads(r.read())["task"]
        except Exception:
            task = {"status": "running"}
        if task["status"] in ("succeeded", "failed"):
            return task
        time.sleep(1.0)
    return {"status": "timeout", "error": "timeout"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--dir", default="eval_minor")
    ap.add_argument("--out", default="")
    ap.add_argument("--max", type=int, default=15)
    args = ap.parse_args()
    d = BASE_ROOT / args.dir
    imgs = sorted(d.glob("*.jpg"))[: args.max]
    ok, rows = 0, []
    for img in imgs:
        truth = img.name.split("_")[0]
        print(f">> {img.name}（{truth}）...")
        task = analyze(args.port, img)
        if task["status"] != "succeeded":
            rows.append({"file": img.name, "truth": truth, "error": task.get("error", task["status"])})
            print(f"   !! {task.get('error', task['status'])}")
            continue
        top = (task.get("candidates") or [{}])[0]
        top_c = top.get("country", "")
        c = top_c == truth
        ok += c
        rows.append({"file": img.name, "truth": truth, "top1": top_c, "correct": c,
                     "elapsed_ms": task.get("elapsed_ms", 0)})
        print(f"   真值={truth:<12} Top1={top_c:<16} {'✓' if c else '✗'}")
        time.sleep(0.3)
    acc = round(ok / len(rows), 3) if rows else 0
    print(f"\n=== 端口{args.port} | {args.dir} | {ok}/{len(rows)} = {acc:.1%} ===")
    if args.out:
        out = Path(args.out)
        out.write_text(json.dumps({"summary": {"total": len(rows), "correct": ok, "accuracy": acc}, "rows": rows},
                                  ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"已保存 {out}")


if __name__ == "__main__":
    sys.exit(main())
