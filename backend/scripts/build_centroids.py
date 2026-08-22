"""从 Natural Earth 国家边界数据计算各国几何中心（质心），生成 centroids.py。

用法（backend/ 下）：
    python scripts/build_centroids.py              # 下载边界数据并生成
    python scripts/build_centroids.py --skip-dl    # 使用已缓存的数据重新生成

产出：backend/app/geokb/centroids.py（COUNTRY_GEOM_CENTERS 字典）
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CACHE = REPO / "data" / "geokb" / "ne_countries.json"
OUT = REPO / "app" / "geokb" / "centroids.py"

SOURCES = [
    "https://raw.githubusercontent.com/martynafford/natural-earth-geojson/master/110m/cultural/ne_110m_admin_0_countries.geojson",
    "https://raw.githubusercontent.com/johan/world.geo.json/master/countries.geo.json",
]

# 源数据国家名 → 本工具规范名
NAME_ALIASES = {
    "United States of America": "United States",
    "USA": "United States",
    "Czech Republic": "Czechia",
    "Czechia": "Czechia",
    "Republic of Korea": "South Korea",
    "South Korea": "South Korea",
    "Russia": "Russia",
    "United Kingdom": "United Kingdom",
    "Vietnam": "Vietnam",
    "Laos": "Laos",
    "Tanzania": "Tanzania",
    "Dominican Republic": "Dominican Republic",
    "Moldova": "Moldova",
    "Taiwan": "Taiwan",
    "United Arab Emirates": "United Arab Emirates",
    "South Africa": "South Africa",
    "Turkey": "Turkey",
    "Macedonia": "Macedonia",  # 未用
    "Iran": "Iran",
    "South Korea": "South Korea",
}

# 跳过：南极洲及会污染质心的岛国记录
SKIP_ADMIN = {"Antarctica", "French Southern and Antarctic Lands", "Svalbard"}

# 我们关心的规范国家（从 countries.py 种子中取）
TARGETS = [
    "United Kingdom", "Ireland", "Germany", "France", "Spain", "Portugal", "Italy",
    "Netherlands", "Belgium", "Switzerland", "Austria", "Poland", "Czechia", "Hungary",
    "Ukraine", "Romania", "Bulgaria", "Greece", "Turkey", "Russia", "Sweden", "Norway",
    "Denmark", "Finland", "Iceland", "Slovakia", "Croatia", "Serbia", "United States",
    "Canada", "Mexico", "Brazil", "Argentina", "Australia", "New Zealand", "Japan",
    "South Korea", "China", "Taiwan", "India", "Thailand", "Vietnam", "Indonesia",
    "Philippines", "South Africa", "Morocco", "Egypt", "United Arab Emirates", "Israel",
    "Saudi Arabia", "Belarus", "Latvia", "Lithuania", "Estonia", "Slovenia",
    "Luxembourg", "Malta", "Cyprus", "Moldova", "Chile", "Peru", "Colombia", "Uruguay",
    "Paraguay", "Ecuador", "Panama", "Costa Rica", "Dominican Republic", "Kenya",
    "Nigeria", "Ghana", "Tanzania", "Ethiopia", "Algeria", "Tunisia", "Jordan",
    "Lebanon", "Iran", "Pakistan", "Bangladesh", "Sri Lanka", "Myanmar", "Cambodia",
    "Laos", "Mongolia", "Kazakhstan", "Azerbaijan", "Georgia", "Armenia", "Malaysia",
    "Singapore",
]


def polygon_centroid(rings: list) -> tuple[float, float, float]:
    """标准多边形质心（planar，x=lon, y=lat）：返回 (lat, lon, 面积)。

    使用带符号面积：外环逆时针为正、孔洞顺时针为负，天然处理空洞；
    个别源数据方向相反时，统一按环面积符号归一化（若总面积为负则整体取反）。
    """
    tot_cx = tot_cy = tot_a = 0.0
    for ring in rings:
        pts = [(p[0], p[1]) for p in ring]
        if len(pts) < 3:
            continue
        a = 0.0
        cx = cy = 0.0
        for i in range(len(pts) - 1):
            x1, y1 = pts[i]
            x2, y2 = pts[i + 1]
            cross = x1 * y2 - x2 * y1
            a += cross
            cx += (x1 + x2) * cross
            cy += (y1 + y2) * cross
        a *= 0.5
        if abs(a) < 1e-9:
            continue
        if a < 0:  # 环方向反转：面积与矩同时取反，保持质心位置不变
            a, cx, cy = -a, -cx, -cy
        tot_a += a
        tot_cx += cx / 6.0
        tot_cy += cy / 6.0
    if abs(tot_a) <= 1e-9:
        return 0.0, 0.0, 0.0
    return tot_cy / tot_a, tot_cx / tot_a, tot_a


def feature_centroid(geom: dict) -> tuple[float, float] | None:
    """要素几何质心：Polygon/MultiPolygon 按面积加权。"""
    if geom.get("type") == "Polygon":
        lat, lon, _ = polygon_centroid(geom["coordinates"])
        return (lat, lon) if lat or lon else None
    if geom.get("type") == "MultiPolygon":
        wlat = wlon = wsum = 0.0
        for poly in geom["coordinates"]:
            lat, lon, area = polygon_centroid(poly)
            wsum += area
            wlat += lat * area
            wlon += lon * area
        if wsum <= 0:
            return None
        return (wlat / wsum, wlon / wsum)
    return None


def main() -> int:
    skip_dl = "--skip-dl" in sys.argv
    if not skip_dl:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        data = None
        for url in SOURCES:
            print(f"下载 {url.split('/')[2]} …", flush=True)
            for attempt in range(4):
                try:
                    import httpx
                    resp = httpx.get(url, timeout=90, follow_redirects=True)
                    if resp.status_code != 200:
                        raise RuntimeError(f"HTTP {resp.status_code}")
                    CACHE.write_bytes(resp.content)
                    data = json.loads(resp.content)
                    print(f"  成功（第{attempt + 1}次尝试）：{len(resp.content)//1024} KB")
                    break
                except Exception as e:
                    print(f"  第{attempt + 1}次失败：{str(e)[:80]}")
                    import time
                    time.sleep(2)
            if data is not None:
                break
        if data is None:
            print("所有下载源失败，无法生成；可用 --skip-dl 使用缓存。")
            return 1
    else:
        data = json.loads(CACHE.read_text(encoding="utf-8"))

    # 名称 → 要素
    by_name: dict[str, dict] = {}
    for feat in data.get("features", []):
        props = feat.get("properties") or {}
        name = props.get("ADMIN") or props.get("name") or props.get("NAME") or ""
        if name in SKIP_ADMIN:
            continue
        canonical = NAME_ALIASES.get(name, name)
        by_name.setdefault(canonical, feat)

    centers: dict[str, tuple[float, float]] = {}
    missing: list[str] = []
    for target in TARGETS:
        feat = by_name.get(target)
        if feat is None:
            # 大小写/变体兜底
            feat = next((f for k, f in by_name.items() if k.lower() == target.lower()), None)
        if feat is None:
            missing.append(target)
            continue
        c = feature_centroid(feat.get("geometry") or {})
        if c is None:
            missing.append(target)
            continue
        lat, lon = round(c[0], 4), round(c[1], 4)
        centers[target] = (lat, lon)

    # 生成模块
    lines = ['"""由 scripts/build_centroids.py 自动生成：各国几何中心（质心）。\n请勿手改；重新生成：python scripts/build_centroids.py\n"""\n']
    lines.append("COUNTRY_GEOM_CENTERS: dict[str, tuple[float, float]] = {")
    for name in sorted(centers):
        lat, lon = centers[name]
        lines.append(f'    "{name}": ({lat}, {lon}),')
    lines.append("}")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n生成 {OUT}：{len(centers)} 国")
    if missing:
        print("缺失（将回退首都）：", ", ".join(missing))
    return 0


if __name__ == "__main__":
    sys.exit(main())
