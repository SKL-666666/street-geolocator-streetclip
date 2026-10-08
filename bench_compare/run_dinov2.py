"""C: DINOv2-large 检索式国家级评测（leave-one-out）。
DINOv2 无文本塔，用图像特征在 bench_final 内部检索最近邻投票国家。
公平对比: 同样 leave-one-out, CLIP特征 vs DINOv2特征, 看死区图谁更强。
"""
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
W = os.path.join(HERE, "weights", "dinov2")
BENCH = os.path.join(HERE, "bench_final")
K = 5


def norm_country(name):
    n = name.strip().lower()
    alias = {"uk": "united kingdom", "usa": "united states",
             "czech republic": "czechia", "russian federation": "russia",
             "turkiye": "turkey", "republic of korea": "south korea"}
    return alias.get(n, n)


def main():
    from transformers import AutoImageProcessor, AutoModel
    import torch
    from PIL import Image

    t0 = time.time()
    proc = AutoImageProcessor.from_pretrained(W, local_files_only=True)
    model = AutoModel.from_pretrained(W, local_files_only=True).eval()
    load_s = time.time() - t0
    print(f"[load] DINOv2-large {load_s:.1f}s", file=sys.stderr)

    cats = json.load(open(os.path.join(BENCH, "categories.json"), encoding="utf-8"))
    files = list(cats.keys())

    # 提取 CLS 特征
    t_ext = time.time()
    feats = []
    infer = []
    with torch.no_grad():
        for fn in files:
            img = Image.open(os.path.join(BENCH, fn)).convert("RGB")
            inp = proc(images=img, return_tensors="pt")
            t1 = time.time()
            out = model(**inp)
            infer.append((time.time() - t1) * 1000)
            # CLS token (last_hidden_state[:,0])
            f = out.last_hidden_state[:, 0, :].squeeze(0)
            f = f / f.norm()
            feats.append(f.numpy())
    D = np.stack(feats)
    print(f"[extract] {len(D)} feats in {time.time()-t_ext:.1f}s", file=sys.stderr)

    # leave-one-out 检索投票
    total = correct = 0
    dead_correct = 0
    dead_total = 0
    per_cat = {}
    for i, fn in enumerate(files):
        truth = cats[fn]["country"]
        sims = D @ D[i]
        sims[i] = -999
        top = np.argsort(-sims)[:K]
        votes = {}
        for j in top:
            c = cats[files[j]]["country"]
            w = float(max(sims[j], 0))
            votes[c] = votes.get(c, 0) + w
        pred = max(votes.items(), key=lambda x: x[1])[0] if votes else "?"
        hit = norm_country(pred) == norm_country(truth)
        total += 1
        correct += 1 if hit else 0
        cat = cats[fn]["cat"]
        per_cat.setdefault(cat, [0, 0])
        per_cat[cat][1] += 1
        per_cat[cat][0] += 1 if hit else 0
        if not hit:
            print(f"  [miss] {fn}: {pred} | {truth}", file=sys.stderr)

    infer.sort()
    print("\n===== DINOv2-large (leave-one-out检索, 国家级Top-1, CPU) =====")
    for c, (a, b) in per_cat.items():
        print(f"  {c:6s}: {a}/{b} = {100*a/b:.1f}%")
    print(f"  总计: {correct}/{total} = {100*correct/total:.1f}%")
    print(f"  单张: 平均{sum(infer)/len(infer):.0f}ms | 加载{load_s:.1f}s | 提特征{time.time()-t_ext:.0f}s")


if __name__ == "__main__":
    main()
