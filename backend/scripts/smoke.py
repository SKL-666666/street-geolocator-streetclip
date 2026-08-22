"""冒烟测试：生成测试图（含/不含 GPS），走完整 API 流程（需后端已启动）。

用法：
    python scripts/smoke.py                # 全流程：无GPS图 → mock LLM
    python scripts/smoke.py --exif         # 测试 EXIF GPS 快路径
    python scripts/smoke.py --real <路径>  # 用真实图片 + 真实 LLM（需配置 .env）
"""
from __future__ import annotations

import argparse
import io
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8000"


def make_test_image(with_gps: bool = False) -> bytes:
    """生成一张带/不带 GPS 的 JPEG 测试图。"""
    from PIL import Image
    from PIL.ExifTags import IFD

    img = Image.new("RGB", (640, 480), color=(120, 160, 220))
    for x in range(0, 640, 16):
        for y in range(0, 480, 16):
            if (x // 16 + y // 16) % 2 == 0:
                img.putpixel((x, y), (90, 120, 180))

    buf = io.BytesIO()
    if with_gps:
        exif = Image.Exif()
        exif[IFD.GPSInfo] = {
            1: "N",
            2: (48.0, 51.0, 30.0),   # 48°51'30" N（巴黎）
            3: "E",
            4: (2.0, 17.0, 40.0),    # 2°17'40" E
        }
        img.save(buf, format="JPEG", exif=exif)
    else:
        img.save(buf, format="JPEG")
    return buf.getvalue()


def post_file(path: str, data: bytes) -> dict:
    boundary = "----smoketest"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{path}"\r\n'
        "Content-Type: image/jpeg\r\n\r\n"
    ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"{BASE}/api/analyze", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return __import__("json").loads(resp.read())


def get_task(task_id: str, timeout: float = 60) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with urllib.request.urlopen(f"{BASE}/api/tasks/{task_id}", timeout=10) as resp:
            task = __import__("json").loads(resp.read())["task"]
        if task["status"] in ("succeeded", "failed"):
            return task
        time.sleep(0.5)
    raise TimeoutError("任务超时")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exif", action="store_true", help="只测 EXIF 路径（需用 --real 提供带 GPS 的真实图片）")
    ap.add_argument("--gps", action="store_true", help="用内置生成器构造带 EXIF GPS 的测试图")
    ap.add_argument("--real", type=str, help="用真实图片路径测试")
    args = ap.parse_args()

    with urllib.request.urlopen(f"{BASE}/api/health", timeout=10) as resp:
        health = __import__("json").loads(resp.read())
    print(f"[health] provider={health['provider']} model={health['model']} mapillary={health['mapillary']}")

    if args.real:
        data = open(args.real, "rb").read()
        name = args.real.split("\\")[-1].split("/")[-1]
    elif args.gps:
        data = make_test_image(with_gps=True)
        name = "smoke_gps.jpg"
    else:
        data = make_test_image()
        name = "smoke_test.jpg"

    task_id = post_file(name, data)["task_id"]
    print(f"[submit] task_id={task_id}")
    task = get_task(task_id)
    print(f"[result] status={task['status']} level={task['confidence_level']} elapsed={task['elapsed_ms']}ms")
    print(f"         message={task['message']}")
    if task.get("gps"):
        print(f"         GPS=({task['gps']['lat']}, {task['gps']['lon']}) source={task['gps']['source']}")
    scene = task.get("scene")
    if scene:
        print(f"         summary={scene.get('summary')}")
        for h in scene.get("country_hypotheses", [])[:5]:
            print(f"         country? {h['country']} {h['confidence']:.2f} — {h.get('reasoning', '')[:60]}")
    kb = task.get("geo_kb")
    if kb:
        print("         [Geo-KB 证据矩阵]")
        for c in (kb.get("countries") or [])[:5]:
            print(f"           {c['country']}: llm={c['llm_confidence']:.2f} kb={c['kb_score']:.2f} "
                  f"final={c['final_score']:.2f}")
            for s in c.get("supporting_clues", [])[:3]:
                print(f"             + {s}")
            for s in c.get("contradicting_clues", [])[:2]:
                print(f"             - {s}")
    for f in task.get("facts") or []:
        print(f"         [tool:{f['tool']}] {f['query']}: {f['summary']}")
    print(f"         candidates={len(task.get('candidates') or [])}")

    if task["status"] != "succeeded":
        print(f"         error={task.get('error')}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
