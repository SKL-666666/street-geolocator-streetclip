"""KartaView 街景客户端单元测试（mock httpx 响应，不依赖网络）。"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.streetview.kartaview import KartaViewClient, SVImage


def _photo(**overrides) -> dict:
    base = {
        "id": "470385",
        "lat": "48.859002",
        "lng": "2.293298",
        "heading": "324.42",
        "shotDate": "2016-03-23 09:33:51.000",
        "dateAdded": "2016-03-23 08:33:51",
        "distance": "14.71",
        "imageThUrl": "https://cdn.kartaview.org/pr:sharp/thumb",
        "imageLthUrl": "https://cdn.kartaview.org/pr:sharp/lth",
        "imageProcUrl": "https://cdn.kartaview.org/pr:sharp/proc",
        "fileurlTh": "https://storage2.openstreetcam.org/files/photo/th.jpg",
        "fileurlProc": "https://storage2.openstreetcam.org/files/photo/proc.jpg",
        "fileurl": "https://storage2.openstreetcam.org/files/photo/{{sizeprefix}}/x.jpg",
        "sequenceId": "1282",
    }
    base.update(overrides)
    return base


def _resp(data, has_more=False) -> httpx.Response:
    return httpx.Response(
        200,
        json={"status": {"httpCode": 200}, "result": {"data": data, "hasMoreData": has_more}},
    )


def _client(handler) -> KartaViewClient:
    return KartaViewClient(timeout=5, transport=httpx.MockTransport(handler))


def _run(coro):
    """在同步测试方法里执行异步客户端调用。"""
    return asyncio.run(coro)


class TestParse:
    def test_full_fields(self):
        img = KartaViewClient._parse(_photo())
        assert img is not None
        assert img.id == "470385"
        assert img.lat == 48.859002
        assert img.lon == 2.293298
        assert img.compass_angle == 324.42
        # shotDate 的 ".000" 毫秒后缀被去掉
        assert img.captured_at == "2016-03-23 09:33:51"
        # 优先 cdn 缩略图；fileurl（含 {{sizeprefix}}）不作为 URL 使用
        assert img.thumb_url == "https://cdn.kartaview.org/pr:sharp/thumb"
        assert img.full_url == "https://cdn.kartaview.org/pr:sharp/proc"

    def test_missing_lat_skipped(self):
        assert KartaViewClient._parse(_photo(lat=None)) is None
        assert KartaViewClient._parse(_photo(lat="abc")) is None

    def test_missing_id_skipped(self):
        assert KartaViewClient._parse(_photo(id="")) is None

    def test_bad_heading_ok(self):
        img = KartaViewClient._parse(_photo(heading="N/A"))
        assert img is not None
        assert img.compass_angle is None

    def test_fallback_urls(self):
        img = KartaViewClient._parse(_photo(imageThUrl="", imageLthUrl="", imageProcUrl=""))
        assert img is not None
        assert img.thumb_url == "https://storage2.openstreetcam.org/files/photo/th.jpg"
        assert img.full_url == "https://storage2.openstreetcam.org/files/photo/proc.jpg"


class TestNearby:
    def test_basic(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path.endswith("/2.0/photo/")
            assert request.url.params["lat"] == "48.8584"
            assert request.url.params["lng"] == "2.2945"
            assert request.url.params["radius"] == "60"
            assert request.url.params["itemsPerPage"] == "2"
            return _resp([_photo(), _photo(id="2", lat="48.86", lng="2.295")])

        client = _client(handler)
        images = _run(client.nearby_with_thumbs(48.8584, 2.2945, radius_m=60, limit=2))
        assert len(images) == 2
        assert images[0].id == "470385"

    def test_limit_truncates(self):
        def handler(request):
            return _resp([_photo(id=f"{i}") for i in range(5)], has_more=False)

        client = _client(handler)
        images = _run(client.nearby_with_thumbs(48.8584, 2.2945, radius_m=60, limit=3))
        assert len(images) == 3

    def test_pagination_until_limit(self):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            page = int(request.url.params["page"])
            if page == 1:
                return _resp([_photo(id="1"), _photo(id="2")], has_more=True)
            return _resp([_photo(id="3")], has_more=False)

        client = _client(handler)
        images = _run(client.nearby_with_thumbs(48.8584, 2.2945, radius_m=60, limit=3))
        assert len(images) == 3
        assert [i.id for i in images] == ["1", "2", "3"]
        assert calls["n"] == 2

    def test_dedupe(self):
        def handler(request):
            return _resp([_photo(id="1"), _photo(id="1"), _photo(id="2")], has_more=False)

        client = _client(handler)
        images = _run(client.nearby_with_thumbs(48.8584, 2.2945, radius_m=60, limit=5))
        assert [i.id for i in images] == ["1", "2"]

    def test_bad_items_skipped(self):
        def handler(request):
            return _resp([_photo(), {"id": "x", "lat": None, "lng": None}], has_more=False)

        client = _client(handler)
        images = _run(client.nearby_with_thumbs(48.8584, 2.2945, radius_m=60, limit=5))
        assert len(images) == 1

    def test_nearest_first_sort(self):
        # 服务端乱序返回时，客户端按到查询点的真实距离升序
        def handler(request):
            return _resp(
                [
                    _photo(id="far", lat="48.87", lng="2.30"),     # ~1.3km
                    _photo(id="near", lat="48.859", lng="2.2945"),  # ~70m
                    _photo(id="mid", lat="48.862", lng="2.295"),    # ~400m
                ],
                has_more=False,
            )

        client = _client(handler)
        images = _run(client.nearby_with_thumbs(48.8584, 2.2945, radius_m=60, limit=5))
        assert [i.id for i in images] == ["near", "mid", "far"]


class TestGracefulDegradation:
    def test_http_error_returns_empty(self):
        def handler(request):
            raise httpx.ConnectError("network unreachable", request=request)

        client = _client(handler)
        assert _run(client.nearby_with_thumbs(48.8584, 2.2945)) == []

    def test_http_500_returns_empty(self):
        def handler(request):
            return httpx.Response(500, text="boom")

        client = _client(handler)
        assert _run(client.nearby_with_thumbs(48.8584, 2.2945)) == []

    def test_bad_json_returns_empty(self):
        def handler(request):
            return httpx.Response(200, text="<html>not json</html>")

        client = _client(handler)
        assert _run(client.nearby_with_thumbs(48.8584, 2.2945)) == []

    def test_unexpected_shape_returns_empty(self):
        def handler(request):
            return httpx.Response(200, json={"weird": True})

        client = _client(handler)
        assert _run(client.nearby_with_thumbs(48.8584, 2.2945)) == []

    def test_timeout_returns_empty(self):
        def handler(request):
            raise httpx.ReadTimeout("read timed out", request=request)

        client = _client(handler)
        assert _run(client.nearby_with_thumbs(48.8584, 2.2945)) == []

    def test_invalid_args_no_network(self):
        # radius<=0 / limit<=0 时不发任何请求，直接空列表
        client = _client(lambda r: pytest.fail("不应发起网络请求"))
        assert _run(client.nearby_with_thumbs(48.8584, 2.2945, radius_m=0)) == []
        assert _run(client.nearby_with_thumbs(48.8584, 2.2945, limit=0)) == []


class TestSyncParity:
    def test_svimage_fields_match_mapillary(self):
        """与 mapillary.SVImage 字段完全一致，便于上层统一处理。"""
        from app.streetview.mapillary import SVImage as MapillarySVImage

        assert set(SVImage.__dataclass_fields__) == set(MapillarySVImage.__dataclass_fields__)
