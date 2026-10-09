"""坐标 → 国家英文名（点落国界多边形优先，失败回退最近世界城市）。

用于用户纠错（双击地图选点）反查真实国家，进而把该图作为带标签参考图加入检索库。
"""
from __future__ import annotations

import json
import os
import threading

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(os.path.dirname(_HERE))
_NE = os.path.join(_BACKEND, "data", "geokb", "ne_countries.json")

_lock = threading.Lock()
_poly = None          # [(name, prepared_geom)]


def _load_polygons():
    global _poly
    if _poly is not None:
        return _poly
    with _lock:
        if _poly is not None:
            return _poly
        try:
            from shapely.geometry import shape
            from shapely.prepared import prep
            d = json.load(open(_NE, encoding="utf-8"))
            _poly = [(f["properties"]["name"], prep(shape(f["geometry"])))
                     for f in d["features"]]
        except Exception:  # noqa: BLE001
            _poly = []
    return _poly


def coord_to_country(lat: float, lon: float) -> str | None:
    """坐标 → 国家英文名。国界多边形包含优先；无命中回退最近世界城市（≤50km）。"""
    if lat is None or lon is None:
        return None
    # 1) 点在国界内
    try:
        from shapely.geometry import Point
        pt = Point(lon, lat)  # shapely: (x=lon, y=lat)
        for name, pg in _load_polygons():
            if pg.contains(pt):
                return name
    except Exception:  # noqa: BLE001
        pass
    # 2) 回退最近城市（城市表带 country 英文名）
    try:
        from .citylib import nearest_city
        near = nearest_city(lat, lon, max_km=50)
        if near:
            return near.get("country") or near.get("country_en")
    except Exception:  # noqa: BLE001
        pass
    return None
