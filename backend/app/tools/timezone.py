"""时区工具：本地解析（timezonefinder，纯 Python 无网络）。"""
from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=1)
def _finder():
    try:
        from timezonefinder import TimezoneFinder
        return TimezoneFinder()
    except ImportError:
        return None


def timezone_at(lat: float, lon: float) -> str | None:
    """坐标 → IANA 时区名（如 Europe/Budapest）。"""
    f = _finder()
    if f is None:
        return None
    try:
        return f.timezone_at(lat=lat, lng=lon)
    except Exception:
        return None
