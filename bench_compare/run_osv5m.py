"""OSV5M baseline 评测：回归 GPS → 最近世界城市反查国家。
手动加载 pytorch_model.bin（绕过 hub_mixin 的文件名检测）。
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "street-geolocator-streetclip"))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "osv5m_code"))
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from run_geoclip import coord_to_country, norm_country  # noqa: E402


def get_benches():
    return [os.path.join(os.path.dirname(os.path.abspath(__file__)), "bench_final")]
    return [
        os.path.join(ROOT, "..", "bench50_hd"),
        os.path.join(ROOT, "..", "bench_hard"),
    ]


def load_gt(d):
    return json.load(open(os.path.join(d, "ground_truth.json"), encoding="utf-8"))


def load_osv5m():
    import torch
    from models.huggingface import Geolocalizer
    wdir = os.path.join(HERE, "weights", "osv5m")
    # 用 config 重建架构（不加载权重）：临时把 model.safetensors 指向空 -> 直接构造
    import omegaconf
    cfg = json.load(open(os.path.join(wdir, "config.json"), encoding="utf-8"))
    m = Geolocalizer(config=cfg)          # 只建架构
    sd = torch.load(os.path.join(wdir, "pytorch_model.bin"),
                    map_location="cpu", weights_only=True)
    m.load_state_dict(sd, strict=False)   # 手动灌权重
    m.eval()
    return m


def main():
    import torch
    from PIL import Image

    t0 = time.time()
    model = load_osv5m()
    load_s = time.time() - t0
    print(f"[load] OSV5M {load_s:.1f}s", file=sys.stderr)

    total = correct = 0
    lat_list = []
    per_bench = {}
    for bench_dir in get_benches():
        name = os.path.basename(bench_dir)
        gt = load_gt(bench_dir)
        b_t = b_c = 0
        for fname, truth in gt.items():
            p = os.path.join(bench_dir, fname)
            if not os.path.exists(p):
                continue
            pil = Image.open(p).convert("RGB")
            x = model.transform(pil).unsqueeze(0)
            t1 = time.time()
            with torch.no_grad():
                gps = model.forward(x)   # forward 会包 {"img": x}；forward_tensor 不会
            lat_list.append((time.time() - t1) * 1000)
            lat = float(gps[0, 0] * 180 / 3.14159)
            lon = float(gps[0, 1] * 180 / 3.14159)
            pred = coord_to_country(lat, lon)
            b_t += 1
            hit = norm_country(pred) == norm_country(truth)
            b_c += 1 if hit else 0
            if not hit:
                print(f"  [miss] {fname}: pred={pred}({lat:.1f},{lon:.1f}) | {truth}",
                      file=sys.stderr)
        per_bench[name] = (b_c, b_t)
        total += b_t
        correct += b_c

    lat_list.sort()
    avg = sum(lat_list) / len(lat_list)
    med = lat_list[len(lat_list) // 2]
    print("\n===== OSV5M baseline (回归GPS→国家, CPU) =====")
    for n, (c, t) in per_bench.items():
        print(f"  {n:14s}: {c}/{t} = {100*c/t:.1f}%")
    print(f"  {'总计':12s}: {correct}/{total} = {100*correct/total:.1f}%")
    print(f"  单张耗时: 平均 {avg:.0f}ms | 中位 {med:.0f}ms | 加载 {load_s:.1f}s")


if __name__ == "__main__":
    main()
