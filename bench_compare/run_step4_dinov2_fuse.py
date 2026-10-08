"""Step4: DINOv2特征 + 高质量图库(85张,13国,与测试集零重叠) 检索辅助。
评测: ① 检索单独 ② 与 StreetCLIP 分数融合(扫α) → bench_final 89张国家级。
"""
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "street-geolocator-streetclip", "backend")))

W_DINO = os.path.join(HERE, "weights", "dinov2")


def norm(s):
    n = s.strip().lower()
    alias = {"uk": "united kingdom", "usa": "united states",
             "czech republic": "czechia", "russian federation": "russia",
             "turkiye": "turkey", "republic of korea": "south korea"}
    return alias.get(n, n)


def main():
    from transformers import AutoImageProcessor, AutoModel
    import torch
    from PIL import Image
    from app.geokb.local_engine import encode_streetclip, _load_engine
    from app.geokb.local_engine import COUNTRIES

    t0 = time.time()
    proc = AutoImageProcessor.from_pretrained(W_DINO, local_files_only=True)
    dino = AutoModel.from_pretrained(W_DINO, local_files_only=True).eval()
    print(f"[load] DINOv2 {time.time()-t0:.1f}s", file=sys.stderr)

    # ---- 建库: 85张参考图 ----
    refs = json.load(open(os.path.join(HERE, "ref_gallery", "refs.json"), encoding="utf-8"))
    t0 = time.time()
    ref_feats = []
    with torch.no_grad():
        for r in refs:
            img = Image.open(r["path"]).convert("RGB")
            inp = proc(images=img, return_tensors="pt")
            f = dino(**inp).last_hidden_state[:, 0, :].squeeze(0)
            ref_feats.append((f / f.norm()).numpy())
    R = np.stack(ref_feats)
    ref_countries = [norm(r["country"]).replace("czech republic", "czechia") for r in refs]
    # 国家名归一到 COUNTRIES 口径
    cname = {norm(c): c for c in COUNTRIES}
    ref_countries = [cname.get(norm(c), c) for c in ref_countries]
    print(f"[build] {len(R)} 张参考图 {time.time()-t0:.0f}s", file=sys.stderr)

    # ---- 测试: bench_final 89张 ----
    cats = json.load(open(os.path.join(HERE, "bench_final", "categories.json"), encoding="utf-8"))
    _, sc_proc, sc_nat_tf = _load_engine()

    results = []  # (truth, sc_full_scores dict, retrieval_scores dict)
    t_dino = t_sc = 0
    for fn, meta in cats.items():
        pil = Image.open(os.path.join(HERE, "bench_final", fn)).convert("RGB")
        truth = norm(meta["country"])
        # DINOv2 检索
        t1 = time.time()
        inp = proc(images=pil, return_tensors="pt")
        with torch.no_grad():
            f = dino(**inp).last_hidden_state[:, 0, :].squeeze(0)
        f = (f / f.norm()).numpy()
        t_dino += time.time() - t1
        sims = R @ f
        top_idx = np.argsort(-sims)[:5]
        ret_scores = {}
        for j in top_idx:
            c = norm(ref_countries[int(j)])
            ret_scores[c] = ret_scores.get(c, 0.0) + float(max(sims[j], 0))
        # StreetCLIP 全量国家分数
        t1 = time.time()
        feat = encode_streetclip(open(os.path.join(HERE, "bench_final", fn), "rb").read())
        sims2 = (feat @ sc_nat_tf.T).squeeze(0)
        sc_scores = {}
        for i, c in enumerate(COUNTRIES):
            s = sims2[i * 3:(i + 1) * 3].mean().item()
            sc_scores[norm(c)] = s
        t_sc += time.time() - t1
        results.append((truth, sc_scores, ret_scores))

    n = len(results)
    # 基线: 纯SC
    sc_ok = sum(1 for t, s, _ in results if max(s, key=s.get) == t)
    # 检索单独
    ret_ok = sum(1 for t, _, r in results if r and max(r, key=r.get) == t)
    print(f"\n样本 {n}")
    print(f"纯 StreetCLIP:     {sc_ok}/{n} = {100*sc_ok/n:.1f}%  (t_sc {t_sc/n:.2f}s/张)")
    print(f"DINOv2检索单独:    {ret_ok}/{n} = {100*ret_ok/n:.1f}%  (t_dino {t_dino/n:.2f}s/张)")

    # 融合: score = sc_norm + alpha * ret_norm (各自归一化到max=1)
    print("\n=== 融合 (sc + α×检索) ===")
    best = (sc_ok, 0.0)
    for alpha in [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.6]:
        ok = 0
        for truth, sc, ret in results:
            sc_max = max(sc.values()) or 1
            fused = {c: v / sc_max for c, v in sc.items()}
            if ret:
                r_max = max(ret.values()) or 1
                for c, v in ret.items():
                    fused[c] = fused.get(c, 0) + alpha * v / r_max
            if max(fused, key=fused.get) == truth:
                ok += 1
        print(f"  α={alpha}: {ok}/{n} = {100*ok/n:.1f}%")
        if ok > best[0]:
            best = (ok, alpha)
    print(f"\n最佳: α={best[1]} → {best[0]}/{n} = {100*best[0]/n:.1f}% (基线 {100*sc_ok/n:.1f}%)")


if __name__ == "__main__":
    main()
