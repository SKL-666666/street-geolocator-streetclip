"""Geo-KB 交叉筛选引擎：把 LLM 提取的线索与事实库对照，产出证据矩阵。

思路（GeoGuessr 玩家方法论的程序化）：
- 每条线索 → 命中国家集合（驱动侧/语言/文字/路牌/后缀/邮筒）
- 多线索交叉 → 交集国家获得高权重；矛盾线索（如"右舵" vs "左侧通行"）扣分
- 与 LLM 假设融合：final = 0.6 * LLM置信度 + 0.4 * KB归一化得分
"""
from __future__ import annotations

import os
import re

from ..schemas import GeoKBResult, KBEvidence, SceneAnalysis
from .countries import (
    COUNTRY_ALIASES,
    DRIVING_LEFT_WORDS,
    DRIVING_RIGHT_WORDS,
    LANG_ALIASES,
    country_zh,
)
from .db import load_database

# 融合权重
W_LLM = 0.6
W_KB = 0.4
# 不在知识库中的国家：LLM 声称无法核实，降信系数（幻觉抑制的关键）
UNVERIFIED_PENALTY = 0.5
# kb 归一化分母：约等于"驾驶侧+语言+后缀"的典型强证据组合（3+2+2）
KB_NORM_DENOM = 8.0
# kb 行过滤：弱证据（且 LLM 未提及）不进矩阵，避免噪声
KB_MIN_NORM = 0.15
# 仅 KB 支持（LLM 未提及）的行需要更强证据（≥2 维度，如驾驶侧+语言）
KB_ONLY_MIN_NORM = 0.5


def _canonical_country(name: str) -> str:
    """国家名规范化：中文/简称 → 种子库英文名。"""
    n = name.strip()
    alias = COUNTRY_ALIASES.get(n)
    if alias:
        return alias
    return n
# 各线索维度权重（证据强度）
W_DRIVING = 3.0      # 驾驶侧：强判别
W_LANGUAGE = 2.0     # 语言：强判别
W_SCRIPT = 2.5       # 文字体系：极强判别（西里尔/希腊/阿拉伯/汉字）
W_SUFFIX = 2.0       # 街道后缀：强判别
W_SIGN = 1.5         # 路牌样式：中强
W_MAILBOX = 1.0      # 邮筒：中
W_BOLLARD = 1.5      # 路桩：中强
W_HYDRANT = 1.0      # 消防栓：中
W_POLE = 1.0         # 电线杆：中
W_ROADMARK = 1.0     # 道路标线：中
W_PLATE = 1.5        # 车牌样式：中强
W_SUN = 2.5          # 太阳阴影/半球：极强（南北半球直接二分）
W_CLIMATE = 2.0      # 气候带：强
W_VEGETATION = 1.5   # 植被：中强
W_TERRAIN = 1.5      # 地形：中强
W_SOIL = 1.0         # 土壤：中
W_CAMERA = 1.5       # 街景相机代数（GeoGuessr 线索）：中强
W_CROP = 1.0         # 农田作物（乡村场景弱辅助）：中
W_SOILTYPE = 1.0     # 土壤类型（WRB）：中
W_POLEMETA = 1.5     # 电线杆特征（pole_meta 库，70+ 国）：中强佐证
W_DETAIL = 1.5       # 国家细节（country_details 库：车牌/路桩/标志/独有物件）：中强佐证

_CACHE: dict | None = None

# A/B 评测开关：EVAL_LEGACY_KB=1 时禁用最近几轮新增的知识层
# （camera 小相机/低相机/天线车、语言指纹 Russian、电线杆 pole_meta、国家细节 country_details），
# 用于"知识库丰富前 vs 后"的严格对照（引擎行为回归旧版）。
_LEGACY = os.environ.get("EVAL_LEGACY_KB") == "1"


def get_kb() -> dict:
    global _CACHE
    if _CACHE is None:
        _CACHE = load_database()
    return _CACHE


def reset_cache() -> None:
    """测试用：清空缓存。"""
    global _CACHE
    _CACHE = None


def _norm_lang(lang: str) -> str:
    """语言别名归一化。"""
    l = lang.strip().lower()
    # 英文原名（忽略大小写）
    alias = LANG_ALIASES.get(lang.strip())
    if alias:
        return alias
    return lang.strip()


def _norm_driving(clue: str) -> str | None:
    t = clue.strip().lower()
    if any(w in t for w in DRIVING_LEFT_WORDS):
        return "left"
    if any(w in t for w in DRIVING_RIGHT_WORDS):
        return "right"
    return None


def cross_filter(scene: SceneAnalysis, llm_hypotheses: dict[str, float] | None = None) -> GeoKBResult:
    """主入口：线索 → 证据矩阵。llm_hypotheses: {国家名: 置信度}（自动规范化别名）。"""
    kb = get_kb()
    # 国家名规范化（中文→英文），同时保留原始名用于回写 scene
    llm_raw = llm_hypotheses or {}
    llm_hypotheses = {_canonical_country(n): c for n, c in llm_raw.items()}

    # ---- 线索提取 ----
    clues: list[tuple[str, str]] = []      # (维度, 线索原文)
    supporting: dict[str, list[str]] = {}  # 国家 → 支持线索
    contradicting: dict[str, list[str]] = {}  # 国家 → 矛盾线索

    # 1) 驾驶侧
    driving = _norm_driving(scene.driving_side or "")
    if driving:
        clues.append(("driving_side", scene.driving_side))
        for name, profile in kb["countries"].items():
            if profile["driving_side"] == driving:
                supporting.setdefault(name, []).append(f"驾驶侧：{scene.driving_side}")
            else:
                contradicting.setdefault(name, []).append(f"驾驶侧矛盾：{scene.driving_side} vs 该国{profile['driving_side']}")

    # 2) 语言
    lang_clues = [_norm_lang(x) for x in scene.languages if x.strip()]
    for lang in lang_clues:
        clues.append(("language", lang))
        for name, profile in kb["countries"].items():
            langs = [l.lower() for l in profile["languages"]]
            if lang.lower() in langs:
                supporting.setdefault(name, []).append(f"语言：{lang}")

    # 3) 文字体系（优先用独立 scripts 字段，其次从语言线索推断）
    script_clues = [_norm_lang(x) for x in scene.scripts if x.strip()]
    if not script_clues:
        script_clues = [x for x in lang_clues if x.lower() in (
            "latin", "cyrillic", "greek", "arabic", "hebrew", "chinese",
            "hangul", "thai", "devanagari", "japanese",
        )]
    for script_clue in script_clues:
        for name, profile in kb["countries"].items():
            scripts = [s.lower() for s in profile["scripts"]]
            if script_clue.lower() in scripts:
                supporting.setdefault(name, []).append(f"文字体系：{script_clue}")

    # 4) 街道后缀（在 visible_text 中找）
    suffix_hits: set[str] = set()
    for text in scene.visible_text:
        t = text.strip()
        for name, profile in kb["countries"].items():
            for suffix in profile["suffixes"]:
                if not suffix:
                    continue
                # 大小写不敏感、词边界匹配（后缀可能带标点）
                if re.search(rf"(?i)(^|[^a-zà-ž]){re.escape(suffix)}[\.\s,，。]?", t):
                    if name not in suffix_hits:
                        suffix_hits.add(name)
                        supporting.setdefault(name, []).append(f"街道后缀「{suffix}」出现在「{t[:40]}」")

    # 5) 路牌/路桩/电线杆/消防栓/标线/车牌关键词
    sign_text = (" ".join(scene.traffic_signs) + " " + " ".join(scene.unique_features)).lower()
    kb_indexes = [
        ("sign_keywords", "路牌样式"),
        ("mailbox_keywords", "物件样式"),
        ("bollard_keywords", "路桩样式"),
        ("hydrant_keywords", "消防栓样式"),
        ("pole_keywords", "电线杆样式"),
        ("roadmark_keywords", "道路标线"),
        ("plate_keywords", "车牌样式"),
    ]
    for index_name, prefix in kb_indexes:
        index = kb.get(index_name) or {}
        for kw, countries in index.items():
            if kw.lower() in sign_text:
                for name in countries:
                    supporting.setdefault(name, []).append(f"{prefix}：{kw}")

    # 6) 自然 × 人文维度库（geo_dims.py，150+ 国）：
    #    气候/植被/地形/土壤/半球（太阳阴影）/路桩/电线杆/道路标线
    from .geo_dims import GEO_DIMS
    geo_text = " ".join(
        scene.vegetation + scene.terrain + scene.soil
        + scene.unique_features + scene.architecture
    ).lower()
    sun = (scene.sun_shadow or "").strip()
    for name, dims in GEO_DIMS.items():
        for dim in ("climate", "vegetation", "terrain", "soil", "bollard", "pole", "roadmark"):
            for kw in dims.get(dim, []):
                if kw.lower() in geo_text:
                    supporting.setdefault(name, []).append(f"{dim}：{kw}")
        if sun:
            hemi = dims.get("hemisphere", [])
            if "北" in sun and "N" in hemi:
                supporting.setdefault(name, []).append("太阳阴影：北半球（阴影朝北）")
            elif "南" in sun and "S" in hemi:
                supporting.setdefault(name, []).append("太阳阴影：南半球（阴影朝南）")

    # 7) 谷歌街景相机代数（GeoGuessr 线索）：识别画质特征 → 覆盖区国家加权
    from .camera_gen import GEN_COUNTRIES, GEN_KEYWORDS
    quality_text = " ".join([
        scene.image_quality or "",
        *scene.unique_features,
        scene.summary or "",
    ]).lower()
    detected_gen = None
    # 按特征强度顺序检测：印度相机 > Gen2 > 低相机 > 小相机 > Gen4 > Gen1
    # （legacy 模式：回到 indian > Gen2 > Gen4 > Gen1，无 smallcam/lowcam）
    gen_order = ("indian", "gen2", "lowcam", "smallcam", "gen4", "gen1")
    if _LEGACY:
        gen_order = ("indian", "gen2", "gen4", "gen1")
    for gen in gen_order:
        if any(kw.lower() in quality_text for kw in GEN_KEYWORDS[gen]):
            detected_gen = gen
            break
    if detected_gen:
        for name in GEN_COUNTRIES.get(detected_gen, []):
            supporting.setdefault(name, []).append(f"相机代数：{detected_gen}（街景车画质特征）")
    # 天线街景车（俄罗斯三代黑/白长天线车）：与代数检测并存，单独追加（legacy 跳过）
    if not _LEGACY and any(kw.lower() in quality_text for kw in GEN_KEYWORDS.get("antenna_car", [])):
        for name in GEN_COUNTRIES.get("antenna_car", []):
            supporting.setdefault(name, []).append("相机代数：antenna_car（俄罗斯三代长天线街景车）")

    # 8) 欧洲作物分布 + WRB 土壤类型（乡村/田野场景弱辅助线索）
    from .europe_crops import CROP_COUNTRIES, CROP_KEYWORDS, SOIL_TYPES
    field_text = " ".join(
        scene.vegetation + scene.terrain + scene.soil
        + scene.unique_features + [scene.summary or ""]
    ).lower()
    for crop, kws in CROP_KEYWORDS.items():
        if any(kw.lower() in field_text for kw in kws):
            for name in CROP_COUNTRIES.get(crop, []):
                supporting.setdefault(name, []).append(f"作物：{crop}（{crop}种植区）")
    for soil, info in SOIL_TYPES.items():
        if any(kw.lower() in field_text for kw in info["kw"]):
            for name in info["countries"]:
                supporting.setdefault(name, []).append(f"土壤类型：{soil}（{info['kw'][0]}分布区）")

    # 9) 语言文字指纹（GeoGuessr 语言学线索）：特殊字母/组合/常见词 → 语言 → 国家
    from .lang_script import LANG_CHAR_CLUES
    visible = " ".join(scene.visible_text)
    if visible.strip():
        vis_low = visible.lower()
        chars = set(visible)
        lang_scores: dict[str, int] = {}
        for lang, clues in LANG_CHAR_CLUES.items():
            if _LEGACY and lang == "Russian":
                continue  # legacy：俄语指纹是最近一轮新增
            score = 0
            has_strong = False
            for ch in clues.get("unique", ""):
                if ch in chars:
                    score += 3
                    has_strong = True
            for ch in clues.get("chars", ""):
                if ch in chars:
                    score += 1
            for dg in clues.get("digraphs", []):
                if dg.lower() in vis_low:
                    score += 2
                    has_strong = True
            for w in clues.get("common", []):
                if w in vis_low:
                    score += 1
            # 门槛：得分 ≥2 且必须命中独有字母或判别组合（防普通英文误触发）
            if score >= 2 and has_strong:
                lang_scores[lang] = score
        for lang, _score in sorted(lang_scores.items(), key=lambda x: -x[1])[:3]:
            for name, profile in kb["countries"].items():
                if lang.lower() in [l.lower() for l in profile.get("languages", [])]:
                    supporting.setdefault(name, []).append(f"文字特征：{lang}（特殊字母/组合/词汇）")

    # 10) 电线杆特征库（pole_meta.py，70+ 国，依据社区"电线杆大全"）：
    #     LLM 的 pole 字段描述与各国特征逐子串匹配，任一命中即弱佐证该国。
    #     倒三角/三叉戟/网状/梯子杆等多国共享样式会同时命中多国（弱线索不锁定）。
    if not _LEGACY:
        from .pole_meta import POLE_META
        pole_text = (scene.pole or "").strip()
        if pole_text and pole_text.lower() not in ("unknown", "empty", "none", "无", "无电线杆", "未看到"):
            pole_low = pole_text.lower()
            for name, meta in POLE_META.items():
                hits: list[str] = []
                for kw in meta.get("unique", []):
                    if kw.lower() in pole_low:
                        hits.append(f"{kw}（独有）")
                for kw in meta.get("features", []):
                    if kw.lower() in pole_low:
                        hits.append(kw)
                if hits:
                    shown = "、".join(hits[:4])
                    supporting.setdefault(name, []).append(
                        f"电线杆特征：{shown}（共命中{len(hits)}项）")

    # 11) 国家细节线索库（country_details.py，12 国高判别细节）：
    #     车牌/路桩/护栏标线/交通标志/独有物件/连锁品牌/植被地形，中文关键词匹配
    if not _LEGACY:
        from .country_details import DETAIL_KEYWORDS
        detail_text = " ".join(
            scene.traffic_signs + scene.unique_features + scene.architecture
            + scene.vegetation + scene.terrain + scene.visible_text
        ).lower()
        if detail_text.strip():
            for kw, names in DETAIL_KEYWORDS.items():
                if kw.lower() in detail_text:
                    for name in names:
                        supporting.setdefault(name, []).append(f"国家细节：{kw}")

    # ---- 打分 ----
    # 候选国家集合 = 有任一线索支持的国家 ∪ LLM 假设的国家
    # （仅"矛盾"而无任何支持的国家，只在 LLM 提过它时才进入矩阵，用于展示"为什么排除"）
    candidates = set(supporting.keys()) | set(llm_hypotheses.keys()) | {
        n for n in contradicting if n in llm_hypotheses
    }
    weight_map = {
        "driving_side": W_DRIVING, "language": W_LANGUAGE,
        "script": W_SCRIPT, "suffix": W_SUFFIX, "sign": W_SIGN, "mailbox": W_MAILBOX,
        "bollard": W_BOLLARD, "hydrant": W_HYDRANT, "pole": W_POLE,
        "roadmark": W_ROADMARK, "plate": W_PLATE,
        "sun": W_SUN, "climate": W_CLIMATE, "vegetation": W_VEGETATION,
        "terrain": W_TERRAIN, "soil": W_SOIL, "camera": W_CAMERA,
        "crop": W_CROP, "soiltype": W_SOILTYPE, "polemeta": W_POLEMETA,
        "detail": W_DETAIL,
    }

    kb_scores: dict[str, float] = {}
    for name in candidates:
        sup = supporting.get(name, [])
        con = contradicting.get(name, [])
        score = 0.0
        for clue in sup:
            dim = _dim_of(clue)
            score += weight_map.get(dim, 1.0)
        # 矛盾惩罚：-2 分/条
        score -= 2.0 * len(con)
        kb_scores[name] = max(score, 0.0)

    # ---- 融合 LLM 假设 ----
    rows: list[KBEvidence] = []
    for name in candidates:
        llm_conf = llm_hypotheses.get(name, 0.0)
        kb_norm = min(1.0, kb_scores[name] / KB_NORM_DENOM)
        min_norm = KB_ONLY_MIN_NORM if llm_conf <= 0 else KB_MIN_NORM
        if kb_norm < min_norm and llm_conf <= 0:
            continue  # 弱证据（<2 维度）且 LLM 未提及 → 噪声，不进矩阵
        unverified = name not in kb["countries"]
        llm_factor = UNVERIFIED_PENALTY if unverified else 1.0
        final = W_LLM * llm_factor * llm_conf + W_KB * kb_norm
        rows.append(KBEvidence(
            country=name,
            country_zh=country_zh(name),
            llm_confidence=round(llm_conf, 3),
            kb_score=round(kb_norm, 3),
            final_score=round(min(final, 1.0), 3),
            unverified=unverified,
            supporting_clues=supporting.get(name, []),
            contradicting_clues=contradicting.get(name, []),
        ))

    rows.sort(key=lambda r: r.final_score, reverse=True)
    return GeoKBResult(countries=rows, method="cross-filter")


def _dim_of(clue: str) -> str:
    if clue.startswith("驾驶侧"):
        return "driving_side"
    if clue.startswith("语言"):
        return "language"
    if clue.startswith("文字体系"):
        return "script"
    if clue.startswith("街道后缀"):
        return "suffix"
    if clue.startswith("路牌样式"):
        return "sign"
    if clue.startswith("物件样式"):
        return "mailbox"
    if clue.startswith("路桩样式"):
        return "bollard"
    if clue.startswith("消防栓样式"):
        return "hydrant"
    if clue.startswith("电线杆样式"):
        return "pole"
    if clue.startswith("电线杆特征"):
        return "polemeta"
    if clue.startswith("国家细节"):
        return "detail"
    if clue.startswith("道路标线"):
        return "roadmark"
    if clue.startswith("车牌样式"):
        return "plate"
    if clue.startswith("太阳阴影"):
        return "sun"
    if clue.startswith("相机代数"):
        return "camera"
    if clue.startswith("作物"):
        return "crop"
    if clue.startswith("土壤类型"):
        return "soiltype"
    if clue.startswith("文字特征"):
        return "language"
    if clue.startswith("climate"):
        return "climate"
    if clue.startswith("vegetation"):
        return "vegetation"
    if clue.startswith("terrain"):
        return "terrain"
    if clue.startswith("soil"):
        return "soil"
    if clue.startswith("bollard"):
        return "bollard"
    if clue.startswith("pole"):
        return "pole"
    if clue.startswith("roadmark"):
        return "roadmark"
    return "other"


def merge_into_scene(result: GeoKBResult, scene: SceneAnalysis) -> None:
    """用融合分数重排 scene.country_hypotheses（按原始名称回写置信度）。"""
    final_map = {r.country: r.final_score for r in result.countries}
    matrix_names = {r.country for r in result.countries}
    for h in scene.country_hypotheses:
        canonical = _canonical_country(h.country)
        if canonical in final_map:
            h.confidence = round(final_map[canonical], 3)
        elif canonical not in matrix_names:
            # LLM 提到但未进矩阵（无任何证据）→ 保留但降为未核实档
            h.confidence = round(min(h.confidence, 0.3), 3)
    scene.country_hypotheses.sort(key=lambda h: h.confidence, reverse=True)
