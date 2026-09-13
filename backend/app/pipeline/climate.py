"""CLIP 视觉特征增强：气候/路面/建筑/驾驶方向/植被 5维判断。

所有特征一次性预计算（永久缓存），每张图仅做一次图像编码 + 5 次向量点积。
每个维度贡献 ≤0.04 分，总共最多 +0.15 分，不会主导其他信号。"""
from __future__ import annotations
import io, torch
from PIL import Image
from typing import Optional

_CACHE = None

# ===== 特征配置：提示词 → 典型国家 + 权重 =====
FEATURES = {
    "climate": {
        "prompts": [f"a photo taken in a {p} environment"
                    for p in ["tropical rainforest", "tropical savanna", "desert",
                              "temperate forest", "boreal forest", "tundra",
                              "mediterranean", "grassland", "mountainous"]],
        "priors": {
            "tropical rainforest": (["Indonesia","Brazil","Thailand","Papua New Guinea","Colombia"], 0.03),
            "tropical savanna": (["Tanzania","Kenya","India","Nigeria"], 0.03),
            "desert": (["Morocco","Egypt","Kazakhstan","Mongolia","Chile","Namibia"], 0.04),
            "temperate forest": (["France","Germany","Poland","United States","Canada","Japan"], 0.02),
            "boreal forest": (["Finland","Sweden","Norway","Canada","Russia"], 0.04),
            "mediterranean": (["Spain","Italy","Greece","Turkey","Morocco"], 0.03),
            "grassland": (["Mongolia","Kazakhstan","Argentina","Australia","South Africa"], 0.03),
            "mountainous": (["Nepal","Peru","Bolivia","Switzerland","Austria","Georgia"], 0.03),
        }
    },
    "road": {
        "prompts": ["a paved modern asphalt road", "an unpaved dirt road",
                     "a cobblestone street", "a highway with painted road markings"],
        "priors": {
            "unpaved": (["Bolivia","Kazakhstan","Mongolia","Papua New Guinea","Tanzania","Peru"], 0.04),
            "cobblestone": (["Czechia","Hungary","Poland","Romania","Austria"], 0.02),
            "highway": (["Germany","France","United States","Japan"], 0.01),
        }
    },
    "arch": {
        "prompts": ["traditional wooden house with pitched roof",
                     "adobe or mud-brick house",
                     "Asian pagoda or temple building",
                     "European stone building with ornate facade"],
        "priors": {
            "wooden": (["Finland","Sweden","Norway","Canada","Russia","Iceland"], 0.03),
            "Adobe": (["Peru","Bolivia","Mexico","Morocco","Jordan"], 0.02),
            "pagoda": (["Japan","China","Thailand","Nepal"], 0.02),
            "stone": (["Austria","Czechia","Hungary","Georgia"], 0.01),
        }
    },
    "drive": {
        "prompts": ["cars driving on the left side of the road",
                     "cars driving on the right side of the road"],
        "priors": {
            "left": (["United Kingdom","Japan","Australia","India","South Africa","Indonesia","Kenya"], 0.04),
        }
    },
    "vegetation": {
        "prompts": ["tropical palm trees vegetation",
                     "cactus and desert succulent plants",
                     "coniferous pine forest in winter",
                     "bamboo forest",
                     "snow-covered winter landscape"],
        "priors": {
            "cactus": (["Chile","Mexico","United States","Morocco"], 0.03),
            "pine": (["Finland","Sweden","Norway","Canada","Russia","Iceland"], 0.03),
            "bamboo": (["Japan","China","Thailand"], 0.03),
            "snow": (["Finland","Iceland","Norway","Canada","Russia"], 0.02),
        }
    }
}


def _get_feats(proc, model):
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    all_feats = {}
    for key, cfg in FEATURES.items():
        texts = cfg["prompts"]
        tin = proc(text=texts, return_tensors="pt", padding=True)
        with torch.no_grad():
            tf = model.get_text_features(**tin)
            if hasattr(tf, "pooler_output"):
                tf = tf.pooler_output
            all_feats[key] = tf / tf.norm(dim=-1, keepdim=True)
    _CACHE = all_feats
    return all_feats


def classify_all(image_bytes: bytes) -> dict:
    """5 维 CLIP 视觉特征 → 合并先验。返回 {priors: {国家: float}, summary: [str]}。"""
    from app.geokb.local_engine import _load_engine
    model, proc, _ = _load_engine()
    feats = _get_feats(proc, model)
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    inputs = proc(images=img, return_tensors="pt")
    with torch.no_grad():
        img_feat = model.get_image_features(**inputs)
        if hasattr(img_feat, "pooler_output"):
            img_feat = img_feat.pooler_output
        img_feat = img_feat / img_feat.norm(dim=-1, keepdim=True)

    all_priors = {}
    summary = []
    for key, tf in feats.items():
        sims = (img_feat @ tf.T).squeeze(0)
        best_idx = sims.argmax().item()
        best_score = sims[best_idx].item()
        if best_score < 0.12:
            continue
        prompt = FEATURES[key]["prompts"][best_idx]
        priors_cfg, weight = FEATURES[key]["priors"].get(prompt, ([], 0))
        for c in priors_cfg:
            all_priors[c] = all_priors.get(c, 0) + weight
        summary.append(f"{key}:{prompt[:30]}({best_score:.2f})")
    return {"priors": all_priors, "summary": summary}
