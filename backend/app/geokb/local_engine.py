"""本地街景国家分类引擎（StreetCLIP ViT-L/14@336，55+ 国，零 API 成本）。

StreetCLIP：CLIP 架构（文本匹配式，泛化好，实测 20 张混合图 70%，远超分类头模型）。
方法：图片向量 vs 各国家文本描述（3 模板）→ 余弦相似度 TopK → 国家候选。
权重：backend/models/streetclip/pytorch_model.bin（1633MB，本地加载，懒加载）。
打包版：权重打进 _internal/models/streetclip（spec 的 datas 收集）。
"""
from __future__ import annotations

import io
import os
import sys
import threading

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import torch
from PIL import Image

if getattr(sys, "frozen", False):
    # 打包版：权重在 _internal/models/streetclip（PyInstaller datas 收集）
    _MEIPASS = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    _MODEL_DIR = os.path.join(_MEIPASS, "models", "streetclip")
else:
    # 开发版：backend/models/streetclip
    _MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "models", "streetclip")

# 国家列表（覆盖 100+ 常见国家；StreetCLIP 文本匹配用）
COUNTRIES = [
    "France", "Italy", "Spain", "Austria", "Germany", "United Kingdom", "Ireland",
    "Portugal", "Netherlands", "Belgium", "Switzerland", "Czechia", "Slovakia",
    "Hungary", "Romania", "Poland", "Ukraine", "Russia", "Bulgaria", "Serbia",
    "Croatia", "Greece", "Turkey", "Sweden", "Norway", "Finland", "Denmark",
    "Iceland", "Estonia", "Latvia", "Lithuania", "Belarus", "Moldova", "Albania",
    "North Macedonia", "Montenegro", "Bosnia and Herzegovina", "Slovenia",
    "China", "Japan", "South Korea", "Taiwan", "Mongolia", "India", "Thailand",
    "Vietnam", "Cambodia", "Laos", "Indonesia", "Malaysia", "Philippines",
    "Singapore", "Myanmar", "Nepal", "Sri Lanka", "Bangladesh", "Kazakhstan",
    "Uzbekistan", "Kyrgyzstan", "Tajikistan", "Iran", "Iraq", "Saudi Arabia",
    "United Arab Emirates", "Israel", "Jordan", "Lebanon", "Qatar", "Oman",
    "United States", "Canada", "Mexico", "Cuba", "Panama", "Costa Rica",
    "Guatemala", "Dominican Republic", "Colombia", "Venezuela", "Ecuador",
    "Peru", "Bolivia", "Chile", "Argentina", "Uruguay", "Paraguay", "Brazil",
    "Egypt", "Morocco", "Tunisia", "Algeria", "South Africa", "Kenya", "Nigeria",
    "Ghana", "Senegal", "Tanzania", "Ethiopia", "Australia", "New Zealand",
    "Papua New Guinea",
]
TEMPLATES = ["a street view photo taken in {}", "a photo taken in {}", "a street in {}"]

_engine = None
_lock = threading.Lock()


def _load_engine():
    global _engine
    if _engine is not None:
        return _engine
    with _lock:
        if _engine is not None:
            return _engine
        from transformers import CLIPModel, CLIPConfig, CLIPProcessor

        # 本地目录优先（打包版 _internal/models/streetclip 含权重+tokenizer；
        # 开发版 backend/models/streetclip 同样完整）。目录缺文件时回退 HF 名。
        if os.path.exists(os.path.join(_MODEL_DIR, "config.json")):
            source = _MODEL_DIR
        else:
            source = "openai/clip-vit-large-patch14-336"
        cfg = CLIPConfig.from_pretrained(source, local_files_only=True)
        model = CLIPModel(cfg)
        sd = torch.load(os.path.join(_MODEL_DIR, "pytorch_model.bin"),
                        map_location="cpu", weights_only=True)
        model.load_state_dict(sd, strict=False)
        model.eval()
        proc = CLIPProcessor.from_pretrained(source, local_files_only=True)
        texts = [t.format(c) for c in COUNTRIES for t in TEMPLATES]
        with torch.no_grad():
            text_inputs = proc(text=texts, return_tensors="pt", padding=True)
            text_feats = model.get_text_features(**text_inputs)
            text_feats = _feat_tensor(text_feats)
        _engine = (model, proc, text_feats)
        return _engine


def classify_countries(image_bytes: bytes, k: int = 5) -> list[dict]:
    """图片 → 国家 TopK：[{"label": 国家英文名, "prob": float, "index": int}]

    tta=True：多裁剪增强（原图+水平翻转+中心80%裁剪，特征平均，PIGEON验证+3~5pp）
    temperature：温度缩放（<1让分布更尖锐，>1更平滑；PIGEON用1.6，推荐0.7）
    """
    model, proc, text_feats = _load_engine()
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")

    if tta:
        # 多裁剪：原图 + 水平翻转 + 中心80%裁剪
        w, h = img.size
        crops = [
            img,
            img.transpose(Image.FLIP_LEFT_RIGHT),
            img.crop((int(w * 0.1), int(h * 0.1), int(w * 0.9), int(h * 0.9)))
        ]
        inputs = proc(images=crops, return_tensors="pt")
        with torch.no_grad():
            feats = _feat_tensor(model.get_image_features(**inputs))
            img_feat = feats.mean(dim=0, keepdim=True)  # 平均特征
            img_feat = img_feat / img_feat.norm(dim=-1, keepdim=True)  # 重新归一化
    else:
        inputs = proc(images=img, return_tensors="pt")
        with torch.no_grad():
            img_feat = _feat_tensor(model.get_image_features(**inputs))

    with torch.no_grad():
        sims = (img_feat @ text_feats.T).squeeze(0)

    # 温度缩放
    if temperature != 1.0:
        sims = sims / temperature

    # 每国家取 3 模板等权平均分
    country_scores = []
    for i, c in enumerate(COUNTRIES):
        s = sims[i * len(TEMPLATES): (i + 1) * len(TEMPLATES)].mean().item()
        country_scores.append((c, s))
    country_scores.sort(key=lambda x: -x[1])
    return [{"label": c, "prob": round(s, 4), "index": i} for i, (c, s) in enumerate(country_scores[:k])]


def model_name() -> str:
    return "StreetCLIP（本地，ViT-L/14@336）"

def _feat_tensor(x):
    """兼容 transformers 版本差异：返回归一化特征向量。"""
    if hasattr(x, "pooler_output"):
        x = x.pooler_output
    elif isinstance(x, (tuple, list)):
        x = x[0]
    import torch.nn.functional as F
    return F.normalize(x, dim=-1)


# ================= 第二级：城市分类（CLIP-B/16 通用零样本） =================
# 实测（8 城街景，已知国家）：CLIP-B/16 城市命中 5/8 > StreetCLIP L/14 2/8，
# 且单张仅 ~0.3s（文本特征编码后图片一次编码）。城市文本用"城市, 国家"组合模板。
_CITY_TEMPLATES = ["a street in {}, {}", "a street view photo taken in {}, {}"]
_city_engine = None
_city_lock = threading.Lock()
# 城市池文本特征缓存（key=(国家, 池规模) → 归一化文本特征矩阵）。
# 文本不随图片变化，跨请求可复用——这是第二级提速的关键（每国省 2-4s 文本编码）。
_city_text_cache: dict[tuple[str, int], "torch.Tensor"] = {}
_city_text_cache_lock = threading.Lock()


def _load_city_engine():
    """懒加载 CLIP-B/16（open_clip，权重随应用打包，无需联网）。"""
    global _city_engine
    if _city_engine is not None:
        return _city_engine
    with _city_lock:
        if _city_engine is not None:
            return _city_engine
        import open_clip
        # 本地目录优先（打包版 _internal/models/clipb16；开发版 backend/models/clipb16）
        city_dir = _city_model_dir()
        if city_dir is not None and os.path.exists(os.path.join(city_dir, "open_clip_model.safetensors")):
            model, _, preprocess = open_clip.create_model_and_transforms(
                f"local-dir:{city_dir}")
        else:
            model, _, preprocess = open_clip.create_model_and_transforms(
                "ViT-B-16", pretrained="openai")
        model.eval()
        _city_engine = (model, preprocess)
        return _city_engine


def _city_model_dir() -> str | None:
    """CLIP-B/16 模型目录（开发版 backend/models/clipb16；打包版 _internal/models/clipb16）。"""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return os.path.join(meipass, "models", "clipb16")
        return None
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "models", "clipb16")


def _city_text_feats(country: str, top_n: int):
    """该国城市池文本特征（缓存，跨请求复用；文本不随图片变）。"""
    global _city_text_cache
    key = (country, top_n)
    with _city_text_cache_lock:
        feats = _city_text_cache.get(key)
        if feats is not None:
            return feats
    import torch
    import open_clip
    model, _ = _load_city_engine()
    cities = _country_cities(country, top_n)
    texts = [t.format(c, country) for c in cities for t in _CITY_TEMPLATES]
    with torch.no_grad():
        tf = model.encode_text(open_clip.tokenize(texts))
        tf = tf / tf.norm(dim=-1, keepdim=True)
    with _city_text_cache_lock:
        _city_text_cache.setdefault(key, tf)
    return tf


def _country_cities(country: str, top_n: int = 20) -> list[str]:
    """国家规范名 → 该国表内城市英文名（7100 城表按人口排序）。

    城市池规模弹性：大国（城市多）自动扩大候选，避免漏掉真实城市；
    小国全部纳入。候选池只服务二级匹配（CLIP 从池里选/LLM 无池），
    与"输出第几城"无关。
    """
    from .cities import CITY_COORDS
    out = []
    for name, v in CITY_COORDS.items():
        if v[2] == country:
            out.append(name)
            if len(out) >= top_n:
                break
    return out


def _city_pool_size(country: str) -> int:
    """按国家表内城市总量决定候选池规模：大国 50，中 30，小国全量。"""
    from .cities import CITY_COORDS
    n = sum(1 for v in CITY_COORDS.values() if v[2] == country)
    if n >= 80:
        return 50
    if n >= 30:
        return 30
    return max(n, 10)


def _encode_image(image_bytes: bytes):
    """图片 → 归一化 CLIP 特征（供多个国家复用，只编码一次）。"""
    import torch
    model, preprocess = _load_city_engine()
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    x = preprocess(img).unsqueeze(0)
    with torch.no_grad():
        imf = model.encode_image(x)
        imf = imf / imf.norm(dim=-1, keepdim=True)
    return imf


def classify_cities(image_bytes: bytes, country: str, k: int = 3,
                    top_n: int | None = None, img_feat=None) -> list[dict]:
    """已知国家 → 城市 TopK（CLIP-B/16 从该国城市池里按街景匹配）。

    返回 [{"label": 城市英文名, "prob": 相似度, "lat": float, "lon": float}]
    top_n=None → 按国家规模弹性（_city_pool_size）。
    img_feat：复用已编码图片特征（多国匹配只编码一次图片）；None 则内部编码。
    """
    import torch
    from .countries import COUNTRY_ALIASES
    from .cities import CITY_COORDS

    country = COUNTRY_ALIASES.get(country, country)
    cities = _country_cities(country, top_n or _city_pool_size(country))
    if not cities:
        return []
    tf = _city_text_feats(country, top_n or _city_pool_size(country))
    imf = img_feat if img_feat is not None else _encode_image(image_bytes)
    with torch.no_grad():
        sims = (imf @ tf.T).squeeze(0)
    scored = []
    for i, c in enumerate(cities):
        s = sims[i * len(_CITY_TEMPLATES): (i + 1) * len(_CITY_TEMPLATES)].max().item()
        scored.append((c, s))
    scored.sort(key=lambda x: -x[1])
    out = []
    for c, s in scored[:k]:
        v = CITY_COORDS.get(c)
        if v is None:
            continue
        out.append({"label": c, "prob": round(s, 4), "lat": v[0], "lon": v[1]})
    return out


async def classify_cities_llm_multi(image_bytes: bytes, countries: list[str]) -> list[dict]:
    """本地 Top3 国家 + 原图 → 云端 LLM 逐个定城市（未必是首都）。

    实测：多国候选一次性 prompt 让 LLM 保守（常全 null）；单国 prompt（"拍摄于 X 国"）
    明显更强（敢猜城市）。因此对每个候选国家**并行**发一次单国调用
    （flashx 并发 3，asyncio.gather 并行 ≈ 单次耗时）。

    输出与输入同序：{"country": 国家, "label": 城市英文名, "lat": 估算纬度或0, "lon": 估算经度或0}
    或 None（该国家说不出城市 / 调用失败）。
    """
    import asyncio
    from .countries import COUNTRY_ALIASES

    countries = [COUNTRY_ALIASES.get(c, c) for c in countries]
    out: list[dict | None] = [None] * len(countries)
    if not countries:
        return out
    try:
        from ..llm.factory import create_provider
        provider = create_provider()

        async def one(c: str) -> dict | None:
            prompt = (
                f"这张街景照片拍摄于 {c}。请仔细观察路牌、店名、地标、建筑风格、"
                f"语言、车牌等线索，判断具体是哪个城市。只输出 JSON："
                f'{{"city": "城市英文名", "lat": 估算纬度(可选), "lon": 估算经度(可选)}}'
            )
            try:
                result = await provider.analyze_image(image_bytes, prompt)
                from ..llm.parsing import extract_json
                d = extract_json(result.content)
                city = str(d.get("city") or "").strip()
                if not city or city.lower() in ("null", "none", "unknown", "不确定", "看不出"):
                    return None
                # 国家校验：LLM 在"拍摄于 X 国"的错误前提下可能惯性答照片真实城市
                # （如问 Algeria 却答 Paris）。城市表能解析且国家不符 → 视为该国说不出。
                from .citylib import city_coords
                hit = city_coords(city)
                if hit and COUNTRY_ALIASES.get(hit[2], hit[2]) != c:
                    return None
                lat = lon = 0.0
                try:
                    lat = float(d.get("lat") or 0)
                except (TypeError, ValueError):
                    lat = 0.0
                try:
                    lon = float(d.get("lon") or 0)
                except (TypeError, ValueError):
                    lon = 0.0
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    lat = lon = 0.0
                return {"country": c, "label": city, "lat": lat, "lon": lon}
            except Exception:  # noqa: BLE001 单次失败不影响其他
                return None

        rows = await asyncio.gather(*(one(c) for c in countries))
        return list(rows)
    except Exception:  # noqa: BLE001 整体失败 → 全 None（上层兜底）
        return out


def city_model_name() -> str:
    return "CLIP-B/16（通用，城市级）"