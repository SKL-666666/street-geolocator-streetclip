"""一次性构建 DINOv2 参考图库特征（85张 → features.npz）。
运行: python scripts/build_dinov2_gallery.py
依赖: backend/app/retrieval/gallery.json + backend/data/dinov2_gallery/images/
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, BACKEND)

GALLERY_JSON = os.path.join(BACKEND, "app", "retrieval", "gallery.json")
IMG_DIR = os.path.join(BACKEND, "data", "dinov2_gallery", "images")
OUT_NPZ = os.path.join(BACKEND, "data", "dinov2_gallery", "features.npz")
MODEL_ID = "facebook/dinov2-large"


def main():
    import numpy as np
    import torch
    from PIL import Image
    from transformers import AutoImageProcessor, AutoModel

    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    t0 = time.time()
    proc = AutoImageProcessor.from_pretrained(MODEL_ID)
    model = AutoModel.from_pretrained(MODEL_ID).eval()
    print(f"[load] DINOv2-large {time.time()-t0:.1f}s")

    entries = json.load(open(GALLERY_JSON, encoding="utf-8"))
    feats, countries = [], []
    with torch.no_grad():
        for e in entries:
            fp = os.path.join(IMG_DIR, e["file"])
            if not os.path.exists(fp):
                print(f"  [skip] 缺图 {e['file']}")
                continue
            img = Image.open(fp).convert("RGB")
            inp = proc(images=img, return_tensors="pt")
            f = model(**inp).last_hidden_state[:, 0, :].squeeze(0)
            feats.append((f / f.norm()).numpy())
            countries.append(e["country"])
    np.savez_compressed(OUT_NPZ,
                        feats=np.stack(feats).astype(np.float32),
                        countries=np.array(countries))
    print(f"[done] {len(feats)} 张 → {OUT_NPZ} ({os.path.getsize(OUT_NPZ)//1024}KB), "
          f"耗时 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
