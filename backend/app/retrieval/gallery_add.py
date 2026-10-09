"""用户纠错 → 检索图库增量入库（方案A）。

双击地图纠错时：把该图 + 反查到的真实国家作为一条参考图加入
data/dinov2_gallery/images/，并把其特征增量追加进 features.npz。
下次相似图检索即可命中这条"人工确认"的参考，实现越用越准。
"""
from __future__ import annotations

import os
import threading

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(os.path.dirname(_HERE))
_IMG_DIR = os.path.join(_BACKEND, "data", "dinov2_gallery", "images")
_NPZ = os.path.join(_BACKEND, "data", "dinov2_gallery", "features.npz")
MODEL_ID = "facebook/dinov2-large"

_lock = threading.Lock()


def _ensure_dirs():
    os.makedirs(_IMG_DIR, exist_ok=True)


def add_correction(image_bytes: bytes, country: str, filename: str = "") -> dict:
    """把一张纠错图作为带标签参考图入库。

    返回 {"ok": bool, "file": str, "country": str, "reason": str}。
    - 图片写入 images/
    - DINOv2 特征追加进 features.npz（含 countries 数组）
    """
    _ensure_dirs()
    if not image_bytes or not country:
        return {"ok": False, "reason": "缺图片或国家"}
    with _lock:
        try:
            import torch
            from PIL import Image
            from transformers import AutoImageProcessor, AutoModel
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "reason": f"依赖缺失: {e}"}

        # 唯一文件名（避免覆盖）
        import hashlib
        h = hashlib.md5(image_bytes).hexdigest()[:10]
        ext = os.path.splitext(filename)[1].lower() or ".jpg"
        if ext not in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
            ext = ".jpg"
        fn = f"corr_{h}{ext}"
        path = os.path.join(_IMG_DIR, fn)

        try:
            with open(path, "wb") as f:
                f.write(image_bytes)
        except OSError as e:
            return {"ok": False, "reason": f"写图失败: {e}"}

        # 提特征
        try:
            proc = AutoImageProcessor.from_pretrained(MODEL_ID)
            model = AutoModel.from_pretrained(MODEL_ID).eval()
            img = Image.open(path).convert("RGB")
            inp = proc(images=img, return_tensors="pt")
            with torch.no_grad():
                fv = model(**inp).last_hidden_state[:, 0, :].squeeze(0)
            fv = (fv / fv.norm()).numpy().astype(np.float32)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "reason": f"提特征失败: {e}"}

        # 追加进 features.npz
        try:
            if os.path.exists(_NPZ):
                d = np.load(_NPZ, allow_pickle=False)
                feats = d["feats"]
                countries = [str(c) for c in d["countries"]]
            else:
                feats = np.zeros((0, fv.shape[0]), dtype=np.float32)
                countries = []
            feats = np.vstack([feats, fv[None, :]])
            countries.append(country)
            np.savez_compressed(_NPZ, feats=feats,
                                countries=np.array(countries))
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "reason": f"更新特征库失败: {e}"}

        # 内存索引热重载（dino_geo 模块持有旧数组 → 使其失效，下次查询重载）
        try:
            from . import dino_geo
            dino_geo.invalidate()
        except Exception:  # noqa: BLE001
            pass

        return {"ok": True, "file": fn, "country": country}
