"""KartaView（原 OpenStreetCam，Grab 运营）免 key 街景数据源客户端。

实测可用端点（2024-11 网络探测，均免 key）：
- 按点搜索：GET https://api.kartaview.org/2.0/photo/
    参数：lat, lng, radius（米）, page（从 1 起）, itemsPerPage（≤100，实测 4~100 可用）
    返回：{"status": {...}, "result": {"data": [{photo}...], "hasMoreData": bool}}
    注意：该接口按距离升序返回，直接覆盖"以点为中心、半径米内"的语义。
- 单张照片：GET https://api.kartaview.org/2.0/photo/{id}
- 序列全部照片：GET https://api.kartaview.org/2.0/sequence/{id}/photos
    （返回该序列所有照片，实测不能带 page/itemsPerPage，会 500）

photo 关键字段（值多为字符串）：
- id / lat / lng / heading（方位角）/ shotDate（拍摄时间）/ dateAdded
- 注意：distance 字段是"序列内相邻照片间距"，不是到查询点的距离
  （到查询点的真实距离由服务端 radius 过滤并升序排序，本客户端也做了兜底排序）
- 缩略图：imageThUrl（小）、imageLthUrl（大），对象存储直连：fileurlTh / fileurlLTh
- 原图：imageProcUrl（处理图）、fileurlProc（对象存储直连）
- 注意 fileurl 含 {{sizeprefix}} 占位符，不能直接当 URL 用；
  已归档照片（status=archived）URL 字段为空，属正常现象。

已失效 / 需鉴权的端点（探测结论，勿用）：
- GET /2.0/photo/bbox、GET /2.0/sequence/bbox → 400 "parsing field \"id\""（路由实为 /{id} 风格）
- POST /2.0/sequence/、POST /2.0/photo/（按 bbox 列序列）→ 401 "Passport is missing"
- GET /2.0/sequence/、GET /2.0/photo/（缺 lat/lng/radius 的列表形态）→ 400 "Restricted access!"
- GET /2.0/sequence/map-matched-tracks → 可用但只返回轨迹折线（无照片/序列 id），无法用于取图

本模块接口与 mapillary.py 对齐：SVImage 字段完全一致；
KartaViewClient.nearby_with_thumbs(lat, lon, radius_m, limit) -> list[SVImage]。
所有网络/解析失败均优雅返回空列表（记录 warning）。
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

API_BASE = "https://api.kartaview.org/2.0"
MAX_PAGES = 5  # 翻页上限，防止异常响应导致无限循环


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """两点球面距离（米），用于结果按"最近优先"排序。"""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


@dataclass
class SVImage:
    id: str
    lat: float
    lon: float
    captured_at: str = ""
    compass_angle: Optional[float] = None
    thumb_url: str = ""
    full_url: str = ""


class KartaViewClient:
    def __init__(self, timeout: float = 15.0, transport: Optional[httpx.AsyncBaseTransport] = None):
        self.timeout = timeout
        # 允许测试注入 MockTransport；业务调用不传即可
        self._transport = transport

    async def nearby_with_thumbs(self, lat: float, lon: float, radius_m: int = 60, limit: int = 8) -> list[SVImage]:
        """以 (lat, lon) 为中心、radius_m 米为半径查询街景影像，附缩略图/原图 URL。"""
        if radius_m <= 0 or limit <= 0:
            return []
        try:
            return await self._search(lat, lon, radius_m, limit)
        except Exception as e:  # noqa: BLE001 —— 网络/解析任何失败都优雅降级
            logger.warning("KartaView 查询失败 (lat=%.6f, lng=%.6f): %s", lat, lon, e)
            return []

    async def _search(self, lat: float, lon: float, radius_m: int, limit: int) -> list[SVImage]:
        images: list[SVImage] = []
        seen: set[str] = set()
        page = 1
        per_page = max(1, min(limit, 100))

        async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client:
            while len(images) < limit and page <= MAX_PAGES:
                resp = await client.get(
                    f"{API_BASE}/photo/",
                    params={
                        "lat": lat,
                        "lng": lon,
                        "radius": radius_m,
                        "page": page,
                        "itemsPerPage": per_page,
                    },
                )
                resp.raise_for_status()
                payload = resp.json()
                result = payload.get("result") or {}
                data = result.get("data") or []
                if not isinstance(data, list):
                    data = []

                for item in data:
                    if len(images) >= limit:
                        break
                    img = self._parse(item)
                    if img is None or img.id in seen:
                        continue
                    seen.add(img.id)
                    images.append(img)

                # 翻页条件：本次有数据且服务器声明还有更多
                if not data or not result.get("hasMoreData"):
                    break
                page += 1

        # 服务端按距查询点距离升序返回；这里再兜底排一次，保证"最近优先"
        images.sort(key=lambda img: _haversine_m(lat, lon, img.lat, img.lon))
        return images[:limit]

    @staticmethod
    def _parse(item: dict) -> Optional[SVImage]:
        """把 KartaView photo 条目转成 SVImage；缺坐标/id 的条目跳过。"""
        try:
            img_id = str(item.get("id") or "").strip()
            lat = float(item.get("lat"))
            lon = float(item.get("lng"))
        except (TypeError, ValueError):
            return None
        if not img_id:
            return None

        heading = item.get("heading")
        try:
            angle = float(heading) if heading not in (None, "") else None
        except (TypeError, ValueError):
            angle = None

        captured = str(item.get("shotDate") or item.get("dateAdded") or "")
        captured = captured.replace(".000", "")  # "2016-03-23 09:33:51.000" -> "2016-03-23 09:33:51"

        thumb = (item.get("imageThUrl") or item.get("imageLthUrl")
                 or item.get("fileurlTh") or "")
        full = (item.get("imageProcUrl") or item.get("fileurlProc")
                or item.get("imageLthUrl") or item.get("fileurlLTh") or "")

        return SVImage(
            id=img_id,
            lat=lat,
            lon=lon,
            captured_at=captured,
            compass_angle=angle,
            thumb_url=thumb,
            full_url=full,
        )
