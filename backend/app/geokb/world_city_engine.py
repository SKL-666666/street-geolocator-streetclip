"""世界城市特征匹配引擎（world/no-cn 模式，独立于全球 Geo-KB 的国家级筛选）。

数据：world_cities.py（由 scripts/gen_city_profiles.py 用 LLM 批量生成，
覆盖人口 Top300 非中国城市 × 6~8 个中文判别关键词）。

逻辑与 cn_engine 的城市档案一致：
- scene 线索文本（植被/建筑/地形/独特物件/可见文字/摘要）与城市关键词子串匹配
- 命中 ≥2 个关键词才注入城市假设（防单关键词巧合）
- 置信度 0.3 + 0.05×命中数（封顶 0.5，低于 LLM 明确假设）
- 已存在的同城假设获得小幅佐证加权（+0.05）
"""
from __future__ import annotations

from ..schemas import CityHypothesis, SceneAnalysis

try:
    from .world_cities import WORLD_CITY_PROFILES
except ImportError:  # 数据未生成时为空（不崩溃）
    WORLD_CITY_PROFILES: list[dict] = []


def match_world_cities(scene: SceneAnalysis, max_cities: int = 4,
                       min_hits: int = 2) -> list[CityHypothesis]:
    """场景线索 → 世界城市假设（按命中数降序，至少命中 min_hits 个关键词）。"""
    if not WORLD_CITY_PROFILES:
        return []
    text = " ".join(
        scene.vegetation + scene.architecture + scene.terrain
        + scene.unique_features + scene.visible_text + [scene.summary or ""]
    ).lower()

    scored: list[tuple[int, dict, list[str]]] = []
    for city in WORLD_CITY_PROFILES:
        hits = [kw for kw in city.get("keywords", []) if kw and kw.lower() in text]
        if len(hits) >= min_hits:
            scored.append((len(hits), city, hits))
    scored.sort(key=lambda x: -x[0])

    from .countries import country_zh

    out: list[CityHypothesis] = []
    for n, city, hits in scored[:max_cities]:
        out.append(CityHypothesis(
            city=city["en"], country=city["country"], country_zh=country_zh(city["country"]),
            lat=city["lat"], lon=city["lon"],
            reasoning=f"城市特征档案命中：{'、'.join(hits[:4])}",
            confidence=min(0.5, 0.3 + 0.05 * n),
        ))
    return out


def merge_world_hypotheses(scene: SceneAnalysis, scope: str = "world") -> int:
    """把世界城市档案匹配结果并入 scene.city_hypotheses（同城去重，佐证加权）。

    除中国大陆模式跳过中国城市（档案本身不含中国，双保险）。
    返回新增假设数量。
    """
    from ..geokb.cn_engine import _same_city

    added = 0
    for h in match_world_cities(scene):
        existing = next((x for x in scene.city_hypotheses
                         if _same_city(x.city, h.city)), None)
        if existing:
            existing.confidence = min(0.95, existing.confidence + 0.05)
            if h.reasoning not in existing.reasoning:
                existing.reasoning = f"{existing.reasoning}；{h.reasoning}"
            continue
        if scope == "no-cn" and h.country == "China":
            continue
        scene.city_hypotheses.append(h)
        added += 1
    if added:
        scene.city_hypotheses.sort(key=lambda h: h.confidence, reverse=True)
    return added
