"""中国城市特征匹配引擎（独立于全球 Geo-KB，仅"仅中国大陆"模式使用）。

两条匹配通道（结果统一并入 scene.city_hypotheses）：
1. match_cn_cities：60 城特征档案（cn_cities.py）关键词匹配，命中 ≥2 词才注入。
2. match_cn_regions：省级/区域线索（cn_regions.py）：
   - 车牌简称（visible_text 中的"粤A"）→ 省份（文字级铁证，置信 0.55）
   - 三位区号（010/020/021...）→ 代表城市（铁证级，置信 0.5）
   - 四位区号首两位 → 大区（弱，0.25）
   - 地名后缀（夼/岙/厝/屯/圩/涌）→ 区域（0.3~0.45）
   - 区域档案关键词（植被/建筑/路灯/路牌/民族文字/饮食）→ 区域（0.3~0.45）
   - 雪景城市（街景常见积雪城市，0.25）
   强线索（车牌/区号）优先注入，总新增 ≤4 城，避免稀释 LLM 自身假设；
   已存在的同城假设获得小幅佐证加权。
"""
from __future__ import annotations

import re

from ..schemas import CityHypothesis, SceneAnalysis
from .cn_cities import CN_CITY_PROFILES
from .cn_regions import (
    CN_AREA_CODE_REGIONS,
    CN_AREA_CODES_3,
    CN_PLACE_SUFFIX_REGIONS,
    CN_PLATE_PROVINCES,
    CN_REGION_PROFILES,
    CN_SNOW_CITIES,
    region_profile,
)

# 车牌：简称（31 省）+ 紧跟拉丁字母（如"粤A"）
_PLATE_RE = re.compile(r"[京津沪渝冀豫云辽黑湘皖新闽赣鄂桂甘晋蒙陕吉贵粤青藏川宁琼][A-Z]")
# 区号：0 开头共 3~4 位数字（完整匹配，避免把 4 位区号误截成 3 位）
_AREA_RE = re.compile(r"(?<![0-9])0(\d{2,4})(?![0-9])")
# 地名后缀：中文词（1~6 字）+ 后缀字
_SUFFIX_RE = re.compile(r"[\u4e00-\u9fff]{1,6}[夼岙厝屯圩涌]")


def _city_hypothesis(cname: str, confidence: float, reasoning: str) -> CityHypothesis | None:
    """中文城市名 → 城市假设（坐标走城市表精确值；解析失败返回 None）。"""
    from ..geokb.citylib import city_coords

    hit = city_coords(cname)
    if hit is None:
        return None
    return CityHypothesis(
        city=cname, country="China", country_zh="中国",
        lat=hit[0], lon=hit[1],
        reasoning=reasoning, confidence=confidence,
    )


def match_cn_cities(scene: SceneAnalysis, max_cities: int = 4,
                    min_hits: int = 2) -> list[CityHypothesis]:
    """场景线索 → 中国城市假设（按命中数降序，至少命中 min_hits 个关键词）。"""
    text = " ".join(
        scene.vegetation + scene.architecture + scene.terrain
        + scene.unique_features + scene.visible_text + [scene.summary or ""]
    ).lower()

    scored: list[tuple[int, dict, list[str]]] = []
    for city in CN_CITY_PROFILES:
        hits = [kw for kw in city["keywords"] if kw.lower() in text]
        if len(hits) >= min_hits:
            scored.append((len(hits), city, hits))
    scored.sort(key=lambda x: -x[0])

    out: list[CityHypothesis] = []
    for n, city, hits in scored[:max_cities]:
        out.append(CityHypothesis(
            city=city["en"], country="China", country_zh="中国",
            lat=city["lat"], lon=city["lon"],
            reasoning=f"城市特征档案命中：{'、'.join(hits[:4])}",
            confidence=min(0.7, 0.3 + 0.1 * n),
        ))
    return out


def match_cn_regions(scene: SceneAnalysis, max_inject: int = 4) -> list[CityHypothesis]:
    """省级/区域线索 → 中国城市假设（强线索优先，总量封顶 max_inject）。"""
    vis = " ".join(scene.visible_text)
    full = " ".join(
        scene.vegetation + scene.architecture + scene.terrain
        + scene.unique_features + scene.languages + scene.scripts
        + scene.visible_text + [scene.summary or ""]
    ).lower()

    cands: list[tuple[str, float, str]] = []      # (城市中文名, 置信, 推理)
    seen_regions: dict[str, list[str]] = {}       # 区域 → 命中线索

    # 1) 车牌简称 → 省份（铁证级）
    for m in _PLATE_RE.finditer(vis):
        prov = CN_PLATE_PROVINCES.get(m.group(0)[0])
        if prov:
            seen_regions.setdefault(prov, []).append(f"车牌{m.group(0)}")

    # 2) 区号
    for m in _AREA_RE.finditer(vis):
        code = "0" + m.group(1)          # 完整区号（3 或 4 位）
        if len(code) == 3 and code in CN_AREA_CODES_3:
            cname = CN_AREA_CODES_3[code][0]
            cands.append((cname, 0.5, f"区号{code}（{cname}）"))
        elif len(code) == 4 and code[:2] in CN_AREA_CODE_REGIONS:
            r = CN_AREA_CODE_REGIONS[code[:2]]
            seen_regions.setdefault(r, []).append(f"区号{code}（{r}大区）")

    # 3) 地名后缀 → 区域
    for m in _SUFFIX_RE.finditer(vis):
        suf = m.group(0)[-1]
        r = CN_PLACE_SUFFIX_REGIONS.get(suf)
        if r:
            seen_regions.setdefault(r, []).append(f"地名后缀「{m.group(0)}」")

    # 4) 区域档案关键词（植被/建筑/路灯/路牌/民族文字/饮食等）
    for profile in CN_REGION_PROFILES:
        hits = [kw for kw in profile["keywords"] if kw.lower() in full]
        if hits:
            seen_regions.setdefault(profile["region"], []).extend(hits)

    # 5) 雪景（街景常见积雪城市，弱线索）
    weather_sum = " ".join(scene.weather + [scene.summary or ""])
    if "积雪" in weather_sum:
        for cname in CN_SNOW_CITIES[:3]:
            cands.append((cname, 0.25, "街景常见积雪城市（弱线索）"))

    # 区域命中 → 代表城市（仅车牌是铁证级；区号大区/档案关键词均为弱线索）
    for region, hits in seen_regions.items():
        profile = region_profile(region)
        if not profile:
            continue
        strong = any("车牌" in h for h in hits)
        conf = 0.55 if strong else min(0.45, 0.3 + 0.05 * (len(hits) - 1))
        n = 1 if strong else 2
        for cname in profile["cities"][:n]:
            cands.append((cname, conf, f"{region}：{'、'.join(hits[:3])}"))

    # 去重（同城取高置信）→ 按置信降序 → 取前 max_inject
    best: dict[str, tuple[float, str]] = {}
    for cname, conf, reason in cands:
        if cname not in best or conf > best[cname][0]:
            best[cname] = (conf, reason)
    ordered = sorted(best.items(), key=lambda kv: -kv[1][0])

    out: list[CityHypothesis] = []
    for cname, (conf, reason) in ordered[:max_inject]:
        h = _city_hypothesis(cname, round(conf, 2), reason)
        if h is not None:
            out.append(h)
    return out


def _same_city(a: str, b: str) -> bool:
    """城市名是否同一城：中文/英文/别名归一化比较，或坐标距离 <0.15°（~16km）。"""
    from ..geokb.citylib import _norm, city_coords

    if _norm(a).lower() == _norm(b).lower():
        return True
    ha, hb = city_coords(a), city_coords(b)
    if ha and hb:
        return abs(ha[0] - hb[0]) < 0.15 and abs(ha[1] - hb[1]) < 0.15
    return False


def merge_cn_hypotheses(scene: SceneAnalysis) -> int:
    """把档案/区域匹配结果并入 scene.city_hypotheses（按城市归一化去重，不覆盖已有假设）。

    已有假设若被区域线索佐证 → 小幅加权（+0.06，封顶 0.95）。
    返回新增假设数量。
    """
    added = 0
    new = match_cn_cities(scene) + match_cn_regions(scene)
    for h in new:
        existing = next((x for x in scene.city_hypotheses if _same_city(x.city, h.city)), None)
        if existing:
            # 区域/档案线索佐证已有假设：小幅加权并追加理由
            existing.confidence = min(0.95, existing.confidence + 0.06)
            if h.reasoning not in existing.reasoning:
                existing.reasoning = f"{existing.reasoning}；{h.reasoning}"
            continue
        scene.city_hypotheses.append(h)
        added += 1
    if added:
        scene.city_hypotheses.sort(key=lambda h: h.confidence, reverse=True)
    return added
