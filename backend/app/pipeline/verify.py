"""A1：LLM 复检闭环 —— 查询图 + 候选街景图拼图，LLM 判定"是否同一地点"。

候选分数调整：确认 ×1.15+0.1（封顶 0.99）/ 否决 ×0.35；无影像候选跳过。
所有失败优雅降级（超时/无图/解析失败均不阻塞主流程）。
"""
from __future__ import annotations

import asyncio
import io

import httpx
from PIL import Image, ImageDraw, ImageFont

from ..config import settings
from ..llm.base import LLMProvider
from ..llm.parsing import extract_json
from ..llm.prompts import VERIFY_PROMPT
from ..schemas import Candidate, ToolFact

MAX_PANELS = 3          # 参与复检的候选上限
THUMB_TIMEOUT = 8.0
PANEL_H = 240


async def download_thumb(url: str) -> bytes | None:
    try:
        async with httpx.AsyncClient(timeout=THUMB_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code == 200 and len(resp.content) > 1000:
                return resp.content
    except Exception:
        pass
    return None


async def _fetch_kartaview_thumbs(candidates: list[Candidate]) -> list[Candidate]:
    """复检专用：用 KartaView 拉候选点附近街景图，挂到候选的 thumbnail_url（不追加进结果）。"""
    try:
        from ..streetview.kartaview import KartaViewClient
        client = KartaViewClient(timeout=8)
        out: list[Candidate] = []
        for c in candidates[:MAX_PANELS]:
            try:
                imgs = await asyncio.wait_for(
                    client.nearby_with_thumbs(c.lat, c.lon, radius_m=100, limit=1),
                    timeout=6.0)
            except Exception:
                continue
            if imgs:
                cc = c.model_copy(deep=True)
                cc.thumbnail_url = imgs[0].thumb_url
                out.append(cc)
        return out
    except Exception:
        return []


def _fit(img: Image.Image, height: int) -> Image.Image:
    w, h = img.size
    if h <= 0:
        return img
    return img.resize((max(1, int(w * height / h)), height), Image.LANCZOS)


def build_montage(query_bytes: bytes, thumbs: list[bytes]) -> tuple[bytes, int]:
    """查询图 + 候选缩略图拼成一行（画布 4 段，第 1 段查询）。返回 (jpeg, 面板数)。"""
    query = Image.open(io.BytesIO(query_bytes)).convert("RGB")
    query = _fit(query, PANEL_H)
    panels = [query]
    for tb in thumbs[:MAX_PANELS]:
        try:
            img = Image.open(io.BytesIO(tb)).convert("RGB")
            panels.append(_fit(img, PANEL_H))
        except Exception:
            continue
    width = sum(p.width for p in panels) + (len(panels) - 1) * 8
    canvas = Image.new("RGB", (width, PANEL_H), (20, 20, 20))
    x = 0
    try:
        font = ImageFont.load_default(size=20)
    except TypeError:  # 旧版 PIL
        font = ImageFont.load_default()
    draw = ImageDraw.Draw(canvas)
    for i, p in enumerate(panels):
        canvas.paste(p, (x, 0))
        draw.ellipse((x + 6, 6, x + 34, 34), fill=(220, 38, 38) if i == 0 else (37, 99, 235))
        draw.text((x + 13, 8), str(i + 1), fill=(255, 255, 255), font=font)
        x += p.width + 8
    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=82)
    return buf.getvalue(), len(panels)


async def run_verify(provider: LLMProvider, query_bytes: bytes,
                     candidates: list[Candidate], timeout: float = 6.0) -> ToolFact:
    """执行复检：返回事实记录（ok=False 表示未执行成功）。"""
    # 候选无缩略图时（结果页回查已关），独立拉 KartaView 街景图供复检（不追加进候选）
    with_thumb = [c for c in candidates if c.thumbnail_url][:MAX_PANELS]
    if not with_thumb:
        with_thumb = await _fetch_kartaview_thumbs(candidates[:MAX_PANELS])
    if not with_thumb:
        return ToolFact(tool="verify", query="街景复检",
                        summary="无候选街景影像可复检", ok=False)

    # 下载缩略图（并行）
    thumbs = await asyncio.gather(*[download_thumb(c.thumbnail_url) for c in with_thumb])
    avail = [(c, tb) for c, tb in zip(with_thumb, thumbs) if tb]
    if not avail:
        return ToolFact(tool="verify", query="街景复检",
                        summary="候选街景缩略图下载失败，跳过复检", ok=False)

    try:
        montage, n_panels = await asyncio.to_thread(build_montage, query_bytes, [tb for _, tb in avail])
    except Exception:
        return ToolFact(tool="verify", query="街景复检",
                        summary="拼图构建失败，跳过复检", ok=False)

    # 面板编号：1=查询图，2..n=候选（按 avail 顺序）
    prompt = VERIFY_PROMPT.replace("图2~图N", f"图2~图{n_panels}")
    try:
        result = await asyncio.wait_for(
            provider.analyze_image(montage, prompt, mime="image/jpeg"), timeout=timeout)
        data = extract_json(result.content)
    except Exception as e:
        return ToolFact(tool="verify", query="街景复检",
                        summary=f"复检调用失败（{type(e).__name__}），保持原判", ok=False)

    # 应用判定
    verdicts = []
    for item in data.get("candidates", []):
        try:
            panel_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        idx = panel_id - 2  # 面板编号 → avail 下标
        if idx < 0 or idx >= len(avail):
            continue
        cand, _ = avail[idx]
        same = bool(item.get("same_location"))
        conf = float(item.get("confidence", 0.0) or 0.0)
        reason = str(item.get("reasoning", ""))[:80]
        if same:
            cand.score = min(0.99, cand.score * 1.15 + 0.1)
            cand.evidence.append(f"✅ LLM 复检确认（{conf:.0%}）：{reason}")
        else:
            # 校准（2026-08）：低置信否决（<50%）多为视角/季节/年份差异导致的误判
            # （实测巴黎候选被 10% 置信否决），从重罚 ×0.35 改为从轻 ×0.85；
            # 高置信否决才重罚 ×0.5，避免"明明对了被复检打下去"的假阴性。
            if conf >= 0.5:
                cand.score *= 0.5
                cand.evidence.append(f"❌ LLM 复检否决（{conf:.0%}）：{reason}")
            else:
                cand.score *= 0.85
                cand.evidence.append(f"⚠️ LLM 复检存疑（{conf:.0%}，低置信否决从轻降权）：{reason}")
        verdicts.append(f"候选#{panel_id - 1}{'确认' if same else '否决'}({conf:.0%})")

    summary = "LLM 复检完成：" + "、".join(verdicts) if verdicts else "复检无有效判定"
    return ToolFact(tool="verify", query="街景复检",
                    summary=summary,
                    results=[{"panel": i + 2, "city": c.city_zh or c.city,
                              "score": round(c.score, 3)} for i, (c, _) in enumerate(avail)],
                    ok=bool(verdicts))
