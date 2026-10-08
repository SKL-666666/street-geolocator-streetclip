"""统一零样本国家分类评测：给定 CLIP 系模型 id，用文本匹配(同 StreetCLIP 思路)
跑 bench50_hd + bench_hard，输出国家级 Top1 + 耗时。
用法: python run_zeroshot.py <model_id> <tag>
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "street-geolocator-streetclip"))
BENCHES = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "bench_final"),
]

# 与 StreetCLIP 一致的国家清单（复用 local_engine.COUNTRIES）
sys.path.insert(0, os.path.join(ROOT, "backend"))
from app.geokb.local_engine import COUNTRIES, TEMPLATES  # noqa: E402


def norm_country(name):
    n = name.strip().lower()
    alias = {
        "uk": "united kingdom", "usa": "united states",
        "united states of america": "united states",
        "czech republic": "czechia", "russian federation": "russia",
        "turkiye": "turkey", "republic of korea": "south korea",
    }
    return alias.get(n, n)


def load_gt(bench_dir):
    with open(os.path.join(bench_dir, "ground_truth.json"), encoding="utf-8") as f:
        return json.load(f)


def run(model_id, tag):
    import torch
    from PIL import Image
    if "siglip" in model_id.lower():
        from transformers import SiglipModel, AutoProcessor
        model = SiglipModel.from_pretrained(model_id, local_files_only=False).eval()
        proc = AutoProcessor.from_pretrained(model_id, local_files_only=False)
        # SigLIP 用 sigmoid 损失：裸点积无效，需 logit_scale * dot + logit_bias
        LOGIT_SCALE = float(model.logit_scale.detach())
        LOGIT_BIAS = float(model.logit_bias.detach())

        def img_emb(img):
            inp = proc(images=img, return_tensors="pt")
            with torch.no_grad():
                return model.get_image_features(**inp)

        def txt_emb(texts):
            inp = proc(text=texts, return_tensors="pt", padding=True)
            with torch.no_grad():
                return model.get_text_features(**inp)
    else:
        from transformers import CLIPModel, CLIPProcessor
        model = CLIPModel.from_pretrained(model_id, local_files_only=False).eval()
        proc = CLIPProcessor.from_pretrained(model_id, local_files_only=False)

        def img_emb(img):
            inp = proc(images=img, return_tensors="pt")
            with torch.no_grad():
                return model.get_image_features(**inp)

        def txt_emb(texts):
            inp = proc(text=texts, return_tensors="pt", padding=True)
            with torch.no_grad():
                return model.get_text_features(**inp)

    t0 = time.time()
    texts = [t.format(c) for c in COUNTRIES for t in TEMPLATES]
    tf = txt_emb(texts)
    tf = tf / (tf.norm(dim=-1, keepdim=True) + 1e-9)
    load_s = time.time() - t0

    total = correct = 0
    lat_list = []
    per_bench = {}
    for bench_dir in BENCHES:
        name = os.path.basename(bench_dir)
        gt = load_gt(bench_dir)
        b_t = b_c = 0
        for fname, truth in gt.items():
            p = os.path.join(bench_dir, fname)
            if not os.path.exists(p):
                continue
            img = Image.open(p).convert("RGB")
            t1 = time.time()
            ie = img_emb(img)
            ie = ie / (ie.norm(dim=-1, keepdim=True) + 1e-9)
            dot = (ie @ tf.T).squeeze(0)
            if "siglip" in model_id.lower():
                sims = LOGIT_SCALE * dot + LOGIT_BIAS
            else:
                sims = dot
            sims = sims.view(len(COUNTRIES), len(TEMPLATES)).mean(dim=1)
            pred = COUNTRIES[int(sims.argmax())]
            lat_list.append((time.time() - t1) * 1000)
            b_t += 1
            hit = norm_country(pred) == norm_country(truth)
            b_c += 1 if hit else 0
            if not hit:
                print(f"  [miss] {fname}: pred={pred} | truth={truth}", file=sys.stderr)
        per_bench[name] = (b_c, b_t)
        total += b_t
        correct += b_c

    lat_list.sort()
    avg = sum(lat_list) / len(lat_list)
    med = lat_list[len(lat_list) // 2]
    print(f"\n===== {tag} ({model_id}) 国家级 Top-1, CPU =====")
    for n, (c, t) in per_bench.items():
        print(f"  {n:14s}: {c}/{t} = {100*c/t:.1f}%")
    print(f"  {'总计':12s}: {correct}/{total} = {100*correct/total:.1f}%")
    print(f"  单张耗时: 平均 {avg:.0f}ms | 中位 {med:.0f}ms | 文本编码+加载 {load_s:.1f}s")


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else sys.argv[1])
