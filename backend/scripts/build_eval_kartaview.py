"""A4：用 KartaView（免 key）构建独立评测集 —— 与 MixVPR 画廊完全不同的城市。

用法：python scripts/build_eval_kartaview.py
产出：data/eval_kartaview/{city}_{n}.jpg + metadata.json
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

OUT_DIR = REPO / "data" / "eval_kartaview"
META = OUT_DIR / "metadata.json"

# 与画廊（Budapest/Kyiv/Warsaw/Prague）不同的城市
CITIES = [
    {"city": "Paris", "country": "France", "lat": 48.8584, "lon": 2.2945},
    {"city": "Berlin", "country": "Germany", "lat": 52.5163, "lon": 13.3777},
    {"city": "Rome", "country": "Italy", "lat": 41.9028, "lon": 12.4964},
    {"city": "Madrid", "country": "Spain", "lat": 40.4168, "lon": -3.7038},
    {"city": "Vienna", "country": "Austria", "lat": 48.2082, "lon": 16.3738},
]
PER_CITY = 8
RADIUS_M = 500  # KartaView 上限 500m（实测 1000+ 报 400）


async def main() -> int:
    from app.streetview.kartaview import KartaViewClient

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    client = KartaViewClient(timeout=20)
    meta: list[dict] = []
    seen_ids: set[str] = set()

    async with httpx.AsyncClient(timeout=25, follow_redirects=True) as http:
        for c in CITIES:
            print(f"── {c['city']} ──", flush=True)
            # 多采样点：中心 + 四向偏移（~0.025° ≈ 2.5km 内各点，radius 500m）
            offsets = [(0, 0), (0.025, 0), (-0.025, 0), (0, 0.025), (0, -0.025),
                       (0.05, 0), (0, 0.05), (-0.05, 0)]
            candidates: list = []
            for dlat, dlon in offsets:
                lat, lon = c["lat"] + dlat, c["lon"] + dlon
                images = await client.nearby_with_thumbs(lat, lon,
                                                         radius_m=RADIUS_M, limit=6)
                for img in images:
                    if img.id in seen_ids:
                        continue
                    seen_ids.add(img.id)
                    candidates.append(img)
                if len(candidates) >= PER_CITY * 2:
                    break
            saved = 0
            for img in candidates:
                if saved >= PER_CITY:
                    break
                url = img.full_url or img.thumb_url
                if not url:
                    continue
                try:
                    resp = await http.get(url)
                    if resp.status_code != 200 or len(resp.content) < 5000:
                        continue
                    fname = f"{c['city']}_{saved + 1}.jpg"
                    (OUT_DIR / fname).write_bytes(resp.content)
                    meta.append({"file": str(OUT_DIR / fname), "city": c["city"],
                                 "country": c["country"], "lat": img.lat, "lon": img.lon})
                    saved += 1
                except Exception:
                    continue
            print(f"  保存 {saved}/{PER_CITY}", flush=True)

    META.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n评测集：{len(meta)} 张 → {META}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
