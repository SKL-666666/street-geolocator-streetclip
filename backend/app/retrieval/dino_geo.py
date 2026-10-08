"""DINOv2 检索先验：参考图库(85张/13国) 最近邻 → 国家证据分。

与 StreetCLIP 分数融合用（2026-10 Step4 实测：α=0.1~0.15 平台 56.2%→61.8%）。
依赖：data/dinov2_gallery/features.npz（scripts/build_dinov2_gallery.py 生成）
      + DINOv2 权重（HuggingFace 缓存）。缺失时静默降级（返回 None）。
"""
from __future__ import annotations

import io
import os
import threading

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))       # .../backend/app/retrieval
_BACKEND = os.path.dirname(os.path.dirname(_HERE))        # .../backend
_FEATURES = os.path.join(_BACKEND, "data", "dinov2_gallery", "features.npz")
MODEL_ID = "facebook/dinov2-large"

_lock = threading.Lock()
_model = None
_proc = None
_feats: np.ndarray | None = None
_countries: list[str] = []
_load_error: str | None = None


def _load() -> bool:
    global _model, _proc, _feats, _countries, _load_error
    if _feats is not None:
        return True
    if _load_error is not None:
        return False
    with _lock:
        if _feats is not None:
            return True
        try:
            if not os.path.exists(_FEATURES):
                _load_error = "features.npz 缺失（先运行 scripts/build_dinov2_gallery.py）"
                return False
            import torch
            from PIL import Image  # noqa: F401
            from transformers import AutoImageProcessor, AutoModel
            data = np.load(_FEATURES, allow_pickle=False)
            _feats = data["feats"]
            _countries = [str(c) for c in data["countries"]]
            _proc = AutoImageProcessor.from_pretrained(MODEL_ID)
            _model = AutoModel.from_pretrained(MODEL_ID).eval()
            return True
        except Exception as e:  # noqa: BLE001 任何失败 → 降级
            _load_error = f"{type(e).__name__}: {e}"
            return False


def available() -> bool:
    return _load()


def retrieve_countries(image_bytes: bytes, k: int = 5) -> dict[str, float] | None:
    """图 → Top-K 参考图国家加权分 {country: score}；不可用时 None。"""
    if not _load():
        return None
    import torch
    from PIL import Image
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        inp = _proc(images=img, return_tensors="pt")
        with torch.no_grad():
            f = _model(**inp).last_hidden_state[:, 0, :].squeeze(0)
        f = f / f.norm()
        sims = (_feats @ f.numpy())
        top = np.argsort(-sims)[:k]
        out: dict[str, float] = {}
        for j in top:
            c = _countries[int(j)]
            out[c] = out.get(c, 0.0) + float(max(sims[j], 0.0))
        return out
    except Exception:  # noqa: BLE001
        return None


def error() -> str | None:
    return _load_error
