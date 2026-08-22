"""Mapillary v4 API 客户端（官方通道，需免费 ML Token）。

文档：https://www.mapillary.com/developer/api-documentation
查询：/images?bbox=lon_min,lat_min,lon_max,lat_max&fields=id,geometry,captured_at,compass_angle
取图：/images/{id}?fields=thumb_256_url,thumb_1024_url
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

API_BASE = "https://graph.mapillary.com"


@dataclass
class SVImage:
    id: str
    lat: float
    lon: float
    captured_at: str = ""
    compass_angle: float | None = None
    thumb_url: str = ""
    full_url: str = ""


class MapillaryClient:
    def __init__(self, token: str, timeout: float = 20.0):
        self.token = token
        self.timeout = timeout

    async def images_near(self, lat: float, lon: float, radius_m: int = 60, limit: int = 8) -> list[SVImage]:
        """以 (lat, lon) 为中心的 bbox 查询影像。"""
        # 粗略 bbox：0.00045° ≈ 50m（与 Netryx 网格间距同量级）
        deg = radius_m / 111_320.0
        bbox = f"{lon - deg},{lat - deg},{lon + deg},{lat + deg}"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                f"{API_BASE}/images",
                params={
                    "access_token": self.token,
                    "bbox": bbox,
                    "fields": "id,geometry,captured_at,compass_angle",
                    "limit": limit,
                },
            )
            resp.raise_for_status()
            payload = resp.json()

        images = []
        for item in payload.get("data", []):
            geom = item.get("geometry") or {}
            coords = geom.get("coordinates") or [0, 0]
            images.append(
                SVImage(
                    id=str(item["id"]),
                    lat=coords[1],
                    lon=coords[0],
                    captured_at=str(item.get("captured_at", "")),
                    compass_angle=item.get("compass_angle"),
                )
            )
        return images

    async def thumbnails(self, image_ids: list[str]) -> dict[str, str]:
        """批量取缩略图 URL（thumb_256_url）。"""
        out: dict[str, str] = {}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for img_id in image_ids:
                try:
                    resp = await client.get(
                        f"{API_BASE}/images/{img_id}",
                        params={
                            "access_token": self.token,
                            "fields": "thumb_256_url,thumb_1024_url",
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    url = data.get("thumb_256_url") or data.get("thumb_1024_url") or ""
                    if url:
                        out[img_id] = url
                except httpx.HTTPError:
                    continue
        return out

    async def nearby_with_thumbs(self, lat: float, lon: float, radius_m: int = 60, limit: int = 8) -> list[SVImage]:
        images = await self.images_near(lat, lon, radius_m, limit)
        if not images:
            return []
        thumbs = await self.thumbnails([img.id for img in images])
        for img in images:
            img.thumb_url = thumbs.get(img.id, "")
        return images
