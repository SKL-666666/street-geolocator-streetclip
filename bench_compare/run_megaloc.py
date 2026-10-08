"""MegaLoc (VPR SOTA, 8448维描述子) 国家级评测。
路线：leave-one-out 检索——每张图在同题库其余图中找 Top-K 最近邻，
      按相似度加权投票其国家。无需外部图库。
CPU, ONNX 322x322。
"""
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "street-geolocator-streetclip"))
W = os.path.join(HERE, "weights", "megaloc")
K = 5


def get_benches():
    return [os.path.join(os.path.dirname(os.path.abspath(__file__)), "bench_final")]
    return [
        os.path.join(ROOT, "..", "bench50_hd"),
        os.path.join(ROOT, "..", "bench_hard"),
    ]


def norm_country(name):
    n = name.strip().lower()
    alias = {"uk": "united kingdom", "usa": "united states",
             "czech republic": "czechia", "russian federation": "russia",
             "turkiye": "turkey", "republic of korea": "south korea"}
    return alias.get(n, n)


def preprocess(img):
    """MegaLoc 预处理：resize 322, ImageNet normalize, CHW。"""
    from PIL import Image
    img = img.resize((322, 322), Image.BILINEAR)
    a = np.asarray(img, dtype=np.float32) / 255.0
    mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
    a = (a - mean) / std
    return a.transpose(2, 0, 1)  # CHW


def main():
    import onnxruntime as ort
    from PIL import Image

    t0 = time.time()
    so = ort.SessionOptions()
    so.intra_op_num_threads = os.cpu_count() or 4
    sess = ort.InferenceSession(os.path.join(W, "megaloc_322x322.onnx"), so,
                                providers=["CPUExecutionProvider"])
    in_name = sess.get_inputs()[0].name
    load_s = time.time() - t0
    print(f"[load] MegaLoc ONNX {load_s:.1f}s", file=sys.stderr)

    # 收集所有图
    items = []
    for bd in get_benches():
        gt = json.load(open(os.path.join(bd, "ground_truth.json"), encoding="utf-8"))
        for fn, truth in gt.items():
            p = os.path.join(bd, fn)
            if os.path.exists(p):
                items.append((p, truth, os.path.basename(bd)))

    # 提所有描述子
    t_ext = time.time()
    descs = []
    infer_list = []
    for p, _, _ in items:
        img = Image.open(p).convert("RGB")
        x = preprocess(img)[None]
        t1 = time.time()
        d = sess.run(None, {in_name: x})[0]
        infer_list.append((time.time() - t1) * 1000)
        descs.append(d[0])  # L2 normalized (在图内)
    D = np.stack(descs)
    print(f"[extract] {len(D)} descs in {time.time()-t_ext:.1f}s", file=sys.stderr)

    # leave-one-out 检索投票
    total = correct = 0
    per_bench = {}
    for i, (p, truth, bname) in enumerate(items):
        sims = D @ D[i]
        sims[i] = -999  # 排除自己
        top = np.argsort(-sims)[:K]
        votes = {}
        for j in top:
            c = items[j][1]
            w = float(sims[j])
            votes[c] = votes.get(c, 0.0) + max(w, 0)
        pred = max(votes.items(), key=lambda x: x[1])[0] if votes else "?"
        total += 1
        hit = norm_country(pred) == norm_country(truth)
        correct += 1 if hit else 0
        if not hit:
            print(f"  [miss] {os.path.basename(p)}: {pred} | {truth}", file=sys.stderr)
        per_bench.setdefault(bname, [0, 0])
        per_bench[bname][1] += 1
        per_bench[bname][0] += 1 if hit else 0

    infer_list.sort()
    avg = sum(infer_list) / len(infer_list)
    print("\n===== MegaLoc (leave-one-out检索, 国家级Top-1, CPU) =====")
    for n, (c, t) in per_bench.items():
        print(f"  {n:14s}: {c}/{t} = {100*c/t:.1f}%")
    print(f"  {'总计':12s}: {correct}/{total} = {100*correct/total:.1f}%")
    print(f"  单张推理: 平均 {avg:.0f}ms | 加载 {load_s:.1f}s | 提特征{time.time()-t_ext:.0f}s")


if __name__ == "__main__":
    main()
