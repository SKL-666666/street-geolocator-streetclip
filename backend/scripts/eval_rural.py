"""荒野/乡村图评测：对比 KartaView 街景回查 开/关 的国家 Top1 正确率。

数据：data/eval_minor（玻利维亚/智利/哈萨克/蒙古/巴布亚新几内亚/坦桑尼亚，真值=文件名国家）。
用法：python scripts/eval_rural.py [--out data/eval_rural.json]
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"
BACKEND = Path(__file__).resolve().parent.parent
DIR = BACKEND / "data" / "eval_minor"


def analyze(img: Path, mode="balanced") -> dict:
    boundary = "----rural" + str(int(time.time() * 1000))
    data = img.read_bytes()
    body = b""
    for n, v in (("mode", mode), ("scope", "world")):
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{n}\"\r\n\r\n{v}\r\n").encode()
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{img.name}\"\r\n"
             "Content-Type: image/jpeg\r\n\r\n").encode()
    body += data + b"\r\n" + f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{BASE}/api/analyze", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        tid = json.loads(r.read())["task_id"]
    t0 = time.monotonic()
    while time.monotonic() - t0 < 120:
        with urllib.request.urlopen(f"{BASE}/api/tasks/{tid}", timeout=30) as r:
            task = json.loads(r.read())["task"]
        if task["status"] in ("succeeded", "failed"):
            return task
        time.sleep(1.0)
    return {"status": "timeout", "error": "timeout"}


def truth_of(name: str) -> str:
    return name.split("_")[0]


def main() -> None:
    out = Path(sys.argv[2] if len(sys.argv) > 2 else BACKEND / "data" / "eval_rural.json")
    imgs = sorted(DIR.glob("*.jpg"))
    rows, ok = [], 0
    for img in imgs:
        truth = truth_of(img.name)
        print(f">> {img.name} （{truth}）...")
        task = analyze(img)
        if task["status"] != "succeeded":
            rows.append({"file": img.name, "truth": truth, "error": task.get("error") or task["status"]})
            print(f"   !! {task.get('error', task['status'])}")
            continue
        top = (task.get("candidates") or [{}])[0]
        top_c = top.get("country", "")
        correct = top_c == truth
        ok += correct
        rows.append({"file": img.name, "truth": truth, "top1": top_c, "correct": correct,
                     "elapsed_ms": task.get("elapsed_ms", 0)})
        print(f"   真值={truth:<12} Top1={top_c:<14} {'✓' if correct else '✗'} {task.get('elapsed_ms', 0)}ms")
        time.sleep(0.3)
    summary = {"total": len(rows), "correct": ok,
               "accuracy_top1": round(ok / len(rows), 3) if rows else 0}
    out.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n=== {ok}/{len(rows)} = {summary['accuracy_top1']:.1%} → {out}")


if __name__ == "__main__":
    sys.exit(main())
