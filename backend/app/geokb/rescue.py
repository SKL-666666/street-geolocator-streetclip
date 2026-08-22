"""知识库"救回"机制：把强判别线索从"佐证"升级为"纠错"。

现状：Geo-KB 的所有维度都是佐证级——只对 LLM 已提及的国家抬分。
若 LLM 描述出了强线索（如"竖琴形杆顶"）却漏掉了正确国家，知识库帮不上忙。

本模块：当某国命中**高精度强线索**但 LLM 假设里没有它时，把该国补成
低置信（0.3）城市假设进入候选，让知识库能"救回漏判"。

只救两类高精度线索（防噪声）：
1. pole_meta 的 unique 特征（文档标注"独有"：希腊竖琴杆顶/澳洲防鼠护套等）
2. country_details 中指向 ≤2 个国家的关键词（如 FORTLEV=巴西；多国共享词如
   "双黄线"→4 国 不救）

相机代数（覆盖多国）、语言指纹（文字 LLM 通常已反映在假设里）不救。
"""
from __future__ import annotations

from ..schemas import CityHypothesis, SceneAnalysis


def _canonical(name: str) -> str:
    from .countries import COUNTRY_ALIASES
    return COUNTRY_ALIASES.get(name, name)


def _first_city_of_country(country: str):
    """国家规范名 → 表内人口第一城 (lat, lon, 英文名, 中文名)。"""
    from .cities import CITY_COORDS
    from .citylib import city_zh

    for name, v in CITY_COORDS.items():
        if v[2] == country:
            return (v[0], v[1], name, city_zh(name))
    return None


def rescue_countries(scene: SceneAnalysis, scope: str = "world") -> list[str]:
    """返回应救回的国家规范名列表（LLM 未提及、但强线索命中的国家）。

    cn 模式返回空（中国定位走 cn_engine，此机制面向世界/除大陆）。
    """
    if scope == "cn":
        return []

    known = {_canonical(h.country) for h in scene.country_hypotheses}
    rescued: list[str] = []

    # 1) 电线杆 unique 特征（pole_meta，70+ 国）：命中即高精度
    from .pole_meta import POLE_META
    pole_text = (scene.pole or "").strip()
    if pole_text and pole_text.lower() not in ("unknown", "empty", "none", "无", "无电线杆", "未看到"):
        pole_low = pole_text.lower()
        for name, meta in POLE_META.items():
            if name in known:
                continue
            if any(kw.lower() in pole_low for kw in meta.get("unique", [])):
                rescued.append(name)

    # 2) 国家细节单指向关键词（country_details：指向 ≤2 国）
    from .country_details import DETAIL_KEYWORDS
    detail_text = " ".join(
        scene.traffic_signs + scene.unique_features + scene.architecture
        + scene.vegetation + scene.terrain + scene.visible_text
    ).lower()
    if detail_text.strip():
        for kw, names in DETAIL_KEYWORDS.items():
            if kw.lower() not in detail_text:
                continue
            for name in names:
                if name not in known and name not in rescued and len(names) <= 2:
                    rescued.append(name)

    return rescued


def apply_rescue(scene: SceneAnalysis, scope: str = "world") -> int:
    """把救回国家转成低置信城市假设，并入 scene.city_hypotheses（去重）。

    返回新增假设数量。
    """
    from ..geokb.cn_engine import _same_city

    added = 0
    for name in rescue_countries(scene, scope):
        hit = _first_city_of_country(name)
        if hit is None:
            continue
        lat, lon, en, zh = hit
        # 去重：已有同城（中文/英文/别名）则跳过
        if any(_same_city(h.city, zh) or _same_city(h.city, en) for h in scene.city_hypotheses):
            continue
        scene.city_hypotheses.append(CityHypothesis(
            city=en, country=name, country_zh=zh,
            lat=lat, lon=lon,
            reasoning=f"知识库强线索救回（LLM 未提及）：{name} 命中独有特征，补入候选",
            confidence=0.3,
        ))
        added += 1
    if added:
        scene.city_hypotheses.sort(key=lambda h: h.confidence, reverse=True)
    return added
