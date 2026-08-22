"""B1：为城市构建街景索引（KartaView 免 key 取图 → MixVPR 嵌入 → numpy 向量库）。

用法（backend/ 下）：
    python scripts/build_index.py --city paris --center 48.8584,2.2945 --radius 3000 --limit 600
    python scripts/build_index.py --city rome --center 41.9028,12.4964 --radius 3000 --limit 600
产出：data/index/{city}.faiss.npy + data/index/{city}.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

OUT_DIR = REPO / "data" / "index"
GRID_STEP_M = 400          # 采样网格步长
QUERY_RADIUS_M = 300       # KartaView 单次查询半径（上限 500）
MAX_QUERIES = 120          # 查询点上限


def grid_points(lat: float, lon: float, radius_m: int) -> list[tuple[float, float]]:
    """以中心生成网格采样点。"""
    deg = radius_m / 111_320.0
    step = GRID_STEP_M / 111_320.0
    pts = []
    y = -deg
    while y <= deg:
        x = -deg
        while x <= deg:
            pts.append((lat + y, lon + x / max(0.7, abs(lat + y) / 45.0)))
            x += step
        y += step
    return pts


async def collect_photos(city: str, center: tuple[float, float], radius_m: int) -> list[dict]:
    from app.streetview.kartaview import KartaViewClient

    client = KartaViewClient(timeout=15)
    seen: set[str] = set()
    photos: list[dict] = []
    pts = grid_points(*center, radius_m)[:MAX_QUERIES]
    print(f"采样点 {len(pts)} 个", flush=True)
    for i, (lat, lon) in enumerate(pts):
        try:
            images = await client.nearby_with_thumbs(lat, lon,
                                                     radius_m=QUERY_RADIUS_M, limit=5)
        except Exception:
            continue
        for img in images:
            if img.id in seen:
                continue
            seen.add(img.id)
            url = img.full_url or img.thumb_url
            if not url:
                continue
            photos.append({"id": img.id, "lat": img.lat, "lon": img.lon,
                           "captured_at": img.captured_at, "url": url})
        if (i + 1) % 20 == 0:
            print(f"  已收集 {len(photos)} 张（{i + 1}/{len(pts)}）", flush=True)
    return photos


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", required=True)
    ap.add_argument("--center", required=True, help="lat,lon")
    ap.add_argument("--radius", type=int, default=3000, help="采样半径（米）")
    ap.add_argument("--limit", type=int, default=600, help="建库图片上限")
    ap.add_argument("--skip-fetch", action="store_true", help="跳过取图（用缓存 JSON）")
    args = ap.parse_args()

    lat, lon = map(float, args.center.split(","))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cache_json = OUT_DIR / f"{args.city}.photos.json"

    if args.skip_fetch and cache_json.exists():
        photos = json.loads(cache_json.read_text(encoding="utf-8"))
        print(f"使用缓存照片 {len(photos)} 张")
    else:
        photos = await collect_photos(args.city, (lat, lon), args.radius)
        cache_json.write_text(json.dumps(photos, ensure_ascii=False), encoding="utf-8")
    photos = photos[: args.limit]

    # 下载 + 嵌入
    import httpx

    from app.embedding.mixvpr import MixVPRDescriptor

    desc = MixVPRDescriptor()
    try:
        desc.load()
    except Exception as e:  # noqa: BLE001
        print(f"MixVPR 模型不可用：{e}")
        return 1
    if not desc.available:
        print(f"MixVPR 模型不可用：{desc.error}")
        return 1

    vectors: list = []
    meta: list[dict] = []
    t0 = time.time()
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as http:
        for i, p in enumerate(photos):
            try:
                resp = await http.get(p["url"])
                if resp.status_code != 200 or len(resp.content) < 5000:
                    continue
                vec = desc.embed(resp.content)
                vectors.append(vec)
                meta.append({"lat": p["lat"], "lon": p["lon"],
                             "captured_at": p.get("captured_at", "")})
            except Exception:
                continue
            if (i + 1) % 100 == 0:
                el = time.time() - t0
                print(f"  嵌入 {len(vectors)}/{len(photos)}（{el:.0f}s）", flush=True)

    if not vectors:
        print("无有效向量，建库失败")
        return 1

    import numpy as np

    mat = np.stack(vectors).astype(np.float32)
    mat /= np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9
    np.save(OUT_DIR / f"{args.city}.faiss.npy", mat)
    (OUT_DIR / f"{args.city}.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    print(f"完成：{args.city} 索引 {mat.shape[0]} 张 × {mat.shape[1]} 维 → {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
