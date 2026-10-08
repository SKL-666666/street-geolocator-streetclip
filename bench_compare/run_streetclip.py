"""StreetCLIP 基线评测：bench50_hd + bench_hard 国家级 Top1 准确率 + 单张耗时(CPU)。
复用项目 backend/app/geokb/local_engine.py 的加载与打分逻辑，不重复造轮子。
"""
import io
import json
import os
import sys
import time

# 让脚本能 import 项目后端（app 包在 backend/ 下）
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "street-geolocator-streetclip"))
sys.path.insert(0, os.path.join(ROOT, "backend"))

from app.geokb import local_engine as le  # noqa: E402

BENCHES = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "bench_final"),
]


def load_gt(bench_dir):
    with open(os.path.join(bench_dir, "ground_truth.json"), encoding="utf-8") as f:
        return json.load(f)


def norm_country(name):
    """归一化国家名，消除标签口径差异（UK=United Kingdom 等）。"""
    n = name.strip().lower()
    alias = {
        "uk": "united kingdom",
        "united kingdom of great britain and northern ireland": "united kingdom",
        "usa": "united states",
        "us": "united states",
        "united states of america": "united states",
        "czech republic": "czechia",
        "russia": "russia",
        "russian federation": "russia",
        "south korea": "south korea",
        "korea": "south korea",
        "republic of korea": "south korea",
        "vietnam": "vietnam",
        "turkiye": "turkey",
        "cote divoire": "ivory coast",
        "uae": "united arab emirates",
        "drc": "democratic republic of the congo",
    }
    return alias.get(n, n)


def main():
    t_load0 = time.time()
    engine = le._load_engine()
    load_s = time.time() - t_load0
    print(f"[warmup] StreetCLIP 加载耗时 {load_s:.1f}s", file=sys.stderr)

    total = 0
    correct = 0
    lat_list = []
    per_bench = {}

    for bench_dir in BENCHES:
        name = os.path.basename(bench_dir)
        gt = load_gt(bench_dir)
        b_total = 0
        b_correct = 0
        for fname, truth in gt.items():
            img_path = os.path.join(bench_dir, fname)
            if not os.path.exists(img_path):
                print(f"[skip] 缺图 {img_path}", file=sys.stderr)
                continue
            with open(img_path, "rb") as f:
                data = f.read()
            t0 = time.time()
            top = le.classify_countries(data, k=5)
            dt = (time.time() - t0) * 1000
            lat_list.append(dt)
            pred = top[0]["label"] if top else "?"
            b_total += 1
            hit = norm_country(pred) == norm_country(truth)
            b_correct += 1 if hit else 0
            if not hit:
                print(f"  [miss] {fname}: pred={pred} | truth={truth}", file=sys.stderr)
        per_bench[name] = (b_correct, b_total)
        total += b_total
        correct += b_correct

    lat_list.sort()
    avg = sum(lat_list) / len(lat_list)
    med = lat_list[len(lat_list) // 2]
    print("\n===== StreetCLIP 基线（国家级 Top-1, CPU）=====")
    for name, (c, t) in per_bench.items():
        print(f"  {name:14s}: {c}/{t} = {100*c/t:.1f}%")
    print(f"  {'总计':12s}: {correct}/{total} = {100*correct/total:.1f}%")
    print(f"  单张耗时: 平均 {avg:.0f}ms | 中位 {med:.0f}ms | 加载 {load_s:.1f}s")


if __name__ == "__main__":
    main()
