"""方案 D：Agentic 工具查证编排（确定性多跳，可降级）。

流程：
1. 对 LLM 给出的城市假设做地理编码（geocode）→ 坐标 + 时区
2. 对高辨识度文字/特征做 Wikipedia 查证 → 实体命中
3. 有外部事实时，二次 LLM 复核（FACT_CHECK_PROMPT）修正假设
4. 所有工具失败均优雅降级，不阻塞主流程
"""
from __future__ import annotations

import asyncio
from typing import Optional

from ..config import settings
from ..llm.base import LLMProvider
from ..llm.parsing import extract_json
from ..llm.prompts import build_fact_check_prompt
from ..schemas import Candidate, SceneAnalysis, ToolFact
from ..tools import ToolNetworkError
from ..tools import geocode as geo
from ..tools import timezone as tz
from ..tools import wiki

# 限定每图工具调用次数，防滥用（预算与延时保护）
MAX_GEOCODE = 2
MAX_WIKI = 2

# 网络已断的快速跳过：首次失败后，本进程后续任务直接跳过工具层（省 ~5s/图）
_tools_broken = False


def mark_tools_broken() -> None:
    """外部工具网络不可达时调用（只会在网络级失败时触发）。"""
    global _tools_broken
    _tools_broken = True


def tools_available() -> bool:
    return not _tools_broken

def _safe(value) -> float | None:
    """经纬度安全解析。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if -180.0 <= v <= 180.0 else None


# 描述性词（把整句描述当实体查的过滤器）
_WIKI_STOPWORDS = {    "建筑", "街道", "道路", "风格", "颜色", "外墙", "阳台", "屋顶", "树木", "植被",
    "有", "带", "的", "和", "与", "及", "以及", "常见", "特征", "环境", "位于",
    "the", "a", "an", "street", "road", "building", "style", "with", "and",
}


def _is_entity(text: str) -> bool:
    """启发式：像专有名词的实体才值得百科查证。"""
    t = text.strip()
    if not (3 <= len(t) <= 30):
        return False
    # 描述性句子过滤：含多个空格/逗号/常见描述词
    if any(ch in t for ch in "，。,.、；;:："):
        return False
    words = t.replace("，", " ").replace(",", " ").split()
    if any(w in _WIKI_STOPWORDS for w in words):
        return False
    # 中文实体：不超过 12 字；英文实体：含大写或数字（更像专名）
    if any("\u4e00" <= ch <= "\u9fff" for ch in t):
        return len(t) <= 12
    return any(ch.isupper() or ch.isdigit() for ch in t) or len(words) == 1


async def run_tools_pass(scene: SceneAnalysis) -> list[ToolFact]:
    """执行外部查证，返回事实列表（全部可失败）。

    网络已确认不可达时直接跳过（省 ~5s/图）。
    """
    if _tools_broken:
        return []
    facts: list[ToolFact] = []
    tasks = []

    # 1) 城市假设地理编码（并行）
    for h in scene.city_hypotheses[:MAX_GEOCODE]:
        tasks.append(asyncio.create_task(_geocode_fact(h.city)))

    # 2) 高辨识度文字/特征百科查证（并行）
    query_pool = _pick_wiki_queries(scene)
    for q in query_pool[:MAX_WIKI]:
        tasks.append(asyncio.create_task(_wiki_fact(q)))

    if tasks:
        done = await asyncio.gather(*tasks)
        facts.extend(f for f in done if f is not None)

    return facts


async def _geocode_fact(city: str) -> Optional[ToolFact]:
    try:
        results = await geo.geocode(city, base_url=settings.geocoding_base_url)
    except ToolNetworkError as e:
        mark_tools_broken()
        return ToolFact(tool="geocode", query=city, summary=f"「{city}」地理编码不可用（{e}）", ok=False)
    if not results:
        return ToolFact(tool="geocode", query=city, summary=f"「{city}」地理编码无结果", ok=False)
    best = results[0]
    tz_name = tz.timezone_at(best["lat"], best["lon"])
    summary = f"「{city}」→ {best['lat']:.4f}, {best['lon']:.4f}"
    if tz_name:
        summary += f"（时区 {tz_name}）"
    return ToolFact(tool="geocode", query=city, summary=summary, results=results[:2], ok=True)


async def _wiki_fact(query: str) -> Optional[ToolFact]:
    try:
        results = await wiki.wiki_search(query, base_url=settings.wiki_base_url)
    except ToolNetworkError as e:
        mark_tools_broken()
        return ToolFact(tool="wiki", query=query, summary=f"「{query}」百科不可用（{e}）", ok=False)
    if not results:
        return ToolFact(tool="wiki", query=query, summary=f"「{query}」百科无结果", ok=False)
    top = results[0]
    return ToolFact(
        tool="wiki", query=query,
        summary=f"「{query}」→ {top['title']}",
        results=results, ok=True,
    )


def _pick_wiki_queries(scene: SceneAnalysis) -> list[str]:
    """挑选值得百科查证的实体：可见文字（排除纯路名）与高辨识特征。"""
    queries: list[str] = []
    for text in scene.visible_text:
        if _is_entity(text):
            queries.append(text.strip())
        if len(queries) >= MAX_WIKI:
            break
    for feat in scene.unique_features:
        if _is_entity(feat):
            queries.append(feat.strip())
        if len(queries) >= MAX_WIKI:
            break
    return queries


async def run_fact_check(provider: LLMProvider, scene: SceneAnalysis,
                         facts: list[ToolFact]) -> None:
    """二次 LLM 复核：外部事实 → 修正国家/城市假设（就地更新 scene）。"""
    if not facts or not any(f.ok for f in facts):
        return
    facts_text = "\n".join(
        f"- [{f.tool}] {f.query}: {f.summary}"
        + ("".join(f"\n    · {r.get('title', r.get('name', ''))}: {str(r.get('snippet', r.get('display_name', '')))[:120]}" for r in f.results[:2]))
        for f in facts if f.ok
    )
    if not facts_text.strip():
        return

    prompt = build_fact_check_prompt(scene.summary or "无总结", facts_text)
    try:
        # 纯文本复核：走文本接口（不传占位图，省视觉 token + 更快更稳）
        result = await provider.complete_text(prompt)
        data = extract_json(result.content)
    except Exception:
        return  # 复核失败不影响已有结果

    # 就地更新假设（仅当模型给出了有效输出）
    from ..geokb.countries import country_zh

    new_countries = data.get("country_hypotheses")
    if isinstance(new_countries, list) and new_countries:
        scene.country_hypotheses = [
            CountryHypothesis(
                country=str(c.get("country", "")),
                country_zh=country_zh(str(c.get("country", ""))),
                reasoning=str(c.get("reasoning", "")),
                confidence=float(c.get("confidence", 0.0) or 0.0),
            )
            for c in new_countries if isinstance(c, dict) and c.get("country")
        ]
    new_cities = data.get("city_hypotheses")
    if isinstance(new_cities, list) and new_cities:
        scene.city_hypotheses = [
            CityHypothesis(
                city=str(c.get("city", "")),
                country=str(c.get("country", "")),
                country_zh=country_zh(str(c.get("country", ""))),
                lat=_safe(c.get("lat")),
                lon=_safe(c.get("lon")),
                reasoning=str(c.get("reasoning", "")),
                confidence=float(c.get("confidence", 0.0) or 0.0),
            )
            for c in new_cities if isinstance(c, dict) and c.get("city")
        ]
    if data.get("summary"):
        scene.summary = str(data["summary"])


def candidates_from_geocode(facts: list[ToolFact]) -> list[Candidate]:
    """把地理编码命中的城市转成候选点（有真实坐标！）。"""
    from ..geokb.citylib import city_zh

    out: list[Candidate] = []
    for f in facts:
        if f.tool != "geocode" or not f.ok or not f.results:
            continue
        best = f.results[0]
        out.append(Candidate(
            rank=0, lat=best["lat"], lon=best["lon"],
            score=0.75, source="geocode",
            city=f.query, city_zh=city_zh(f.query),
            accuracy_hint="城市级（地理编码）",
            evidence=[f"地理编码：{f.query} → {best['name'][:60]}"],
        ))
    return out

