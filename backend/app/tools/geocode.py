"""地理编码工具：Nominatim（OSM 免费地理编码，无需 key）。

可配置 GEPCODING_BASE_URL 指向自建实例或替代服务。
"""
from __future__ import annotations

import httpx

from . import ToolNetworkError

DEFAULT_BASE = "https://nominatim.openstreetmap.org"
USER_AGENT = "street-geolocator/0.1 (local geolocation tool)"


async def geocode(query: str, base_url: str = DEFAULT_BASE, timeout: float = 3.0,
                  limit: int = 3) -> list[dict]:
    """地名/店名 → 候选坐标。返回 [{name, lat, lon, display_name, type}]。

    网络级失败抛 ToolNetworkError（调用方据此做快速跳过）；HTTP 错误返回空列表。
    """
    if not query or not query.strip():
        return []
    try:
        async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": USER_AGENT}) as client:
            resp = await client.get(
                f"{base_url}/search",
                params={"q": query.strip(), "format": "jsonv2", "limit": limit,
                        "addressdetails": 0, "accept-language": "en"},
            )
            resp.raise_for_status()
            items = resp.json()
    except ToolNetworkError:
        raise
    except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError):
        raise ToolNetworkError(f"地理编码网络不可达：{base_url}") from None
    except Exception:
        return []
    out = []
    for it in items:
        try:
            out.append({
                "name": it.get("display_name", ""),
                "lat": float(it["lat"]),
                "lon": float(it["lon"]),
                "type": it.get("type", ""),
            })
        except (KeyError, ValueError, TypeError):
            continue
    return out


async def reverse_geocode(lat: float, lon: float, base_url: str = DEFAULT_BASE,
                          timeout: float = 5.0) -> dict | None:
    """坐标 → 地名。"""
    try:
        async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": USER_AGENT}) as client:
            resp = await client.get(
                f"{base_url}/reverse",
                params={"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 10,
                        "accept-language": "en"},
            )
            resp.raise_for_status()
            data = resp.json()
        return {
            "display_name": data.get("display_name", ""),
            "address": data.get("address", {}),
        }
    except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError):
        raise ToolNetworkError(f"地理编码网络不可达：{base_url}") from None
    except Exception:
        return None
