"""植被/气候分类：用 CLIP 文本提示判断图片所属气候区 → 先验国家。"""
from __future__ import annotations

import io
import sys
import torch
from PIL import Image
from typing import Optional

# 气候区 → 典型国家映射
CLIMATE_COUNTRIES = {
    "tropical rainforest": ["Indonesia", "Malaysia", "Brazil", "Colombia", "Papua New Guinea", "Thailand", "Philippines", "Cambodia"],
    "tropical savanna": ["Tanzania", "Kenya", "Nigeria", "India", "Thailand", "Brazil", "Australia"],
    "desert": ["Morocco", "Egypt", "Algeria", "Jordan", "Saudi Arabia", "Iran", "Kazakhstan", "Mongolia", "Chile", "Namibia"],
    "temperate forest": ["France", "Germany", "Poland", "Czechia", "United States", "Canada", "Japan", "South Korea"],
    "boreal forest": ["Finland", "Sweden", "Norway", "Canada", "Russia"],
    "tundra": ["Iceland", "Norway", "Canada", "Russia", "Finland"],
    "mediterranean": ["Spain", "Italy", "Greece", "Turkey", "Morocco", "Tunisia", "Portugal"],
    "grassland": ["Mongolia", "Kazakhstan", "Argentina", "United States", "Australia", "South Africa"],
    "mountainous": ["Nepal", "Peru", "Bolivia", "Switzerland", "Austria", "Georgia", "Kyrgyzstan"],
}

CLIMATE_PROMPTS = [
    "tropical rainforest", "tropical savanna", "desert",
    "temperate forest", "boreal forest", "tundra",
    "mediterranean", "grassland", "mountainous",
]


def classify_climate(image_bytes: bytes) -> Optional[dict]:
    """返回最可能的气候区 + 对应国家先验。"""
    # 复用已加载的 StreetCLIP 模型
    from app.geokb.local_engine import _load_engine, _feat_tensor
    import re

    model, proc, text_feats = _load_engine()  # 用已缓存的模型，不重新加载

    # 构造气候区文本特征
    climate_texts = [f"a photo taken in a {p} environment" for p in CLIMATE_PROMPTS]
    with torch.no_grad():
        # 重新编码气候区文本（一次性）
        tin = proc(text=climate_texts, return_tensors="pt", padding=True)
        cont_feats = model.get_text_features(**tin)
        if hasattr(cont_feats, "pooler_output"):
            cont_feats = cont_feats.pooler_output
        cont_feats = cont_feats / cont_feats.norm(dim=-1, keepdim=True)

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    inputs = proc(images=img, return_tensors="pt")
    with torch.no_grad():
        img_feat = model.get_image_features(**inputs)
        if hasattr(img_feat, "pooler_output"):
            img_feat = img_feat.pooler_output
        img_feat = img_feat / img_feat.norm(dim=-1, keepdim=True)
        sims = (img_feat @ cont_feats.T).squeeze(0)

    # 找到最匹配的气候区
    best_idx = sims.argmax().item()
    best_climate = CLIMATE_PROMPTS[best_idx]
    best_score = sims[best_idx].item()

    # 只有置信度高才返回（避免噪声）
    if best_score < 0.15:
        return None

    priors = {}
    for c in CLIMATE_COUNTRIES.get(best_climate, []):
        priors[c] = 0.08  # 适中权重（避免主导其他信号）

    return {
        "climate": best_climate,
        "confidence": round(best_score, 3),
        "priors": priors,
    }
