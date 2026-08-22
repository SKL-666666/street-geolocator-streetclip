"""MixVPR 地理先验：查询图 → 描述子 → 参考画廊最近邻 → 城市级先验。

画廊（gallery）为 ``data/prior_gallery/`` 下的街景图 + ``metadata.json``：
``[{"file": "budapest_1.jpg", "city": "Budapest", "country": "Hungary",
   "lat": 47.4979, "lon": 19.0402}]``

- PriorEngine 在初始化时逐个 embed 画廊图片并驻留内存（首次构建较慢属正常）。
- 画廊为空或模型不可用时，compute_prior 返回 None（调用方应静默降级）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from ..config import settings
from ..embedding.mixvpr import MixVPRDescriptor

DEFAULT_GALLERY_DIR = settings.data_dir / "prior_gallery"

# 内置候选城市坐标表（画廊元数据缺失坐标时兜底；也可被元数据均值覆盖）
CITY_COORDINATES: dict[str, tuple[float, float, str]] = {
    "Budapest": (47.4979, 19.0402, "Hungary"),
    "Kyiv": (50.4501, 30.5234, "Ukraine"),
    "Warsaw": (52.2297, 21.0122, "Poland"),
    "Prague": (50.0755, 14.4378, "Czech Republic"),
}


@dataclass
class PriorResult:
    """城市级地理先验结果。"""

    city: str
    country: str
    lat: float
    lon: float
    score: float          # 与最相似参考图的余弦相似度（0~1）
    gallery_size: int     # 参与比对的画廊规模


@dataclass
class _GalleryItem:
    file: str
    city: str
    country: str
    lat: float
    lon: float
    vector: np.ndarray    # L2 归一化描述子


class PriorEngine:
    """MixVPR 参考画廊检索引擎。"""

    def __init__(self, gallery_dir: str | Path | None = None,
                 descriptor: Optional[MixVPRDescriptor] = None):
        self.gallery_dir = Path(gallery_dir) if gallery_dir else DEFAULT_GALLERY_DIR
        self.descriptor = descriptor if descriptor is not None else MixVPRDescriptor()
        self._items: list[_GalleryItem] = []
        self._city_coords: dict[str, tuple[float, float]] = {}
        self._build_error: Optional[str] = None
        self._build()

    # ---- 状态 ----

    @property
    def available(self) -> bool:
        """画廊非空且模型可用时才可检索。"""
        return bool(self._items) and self.descriptor.available

    @property
    def gallery_size(self) -> int:
        return len(self._items)

    @property
    def build_error(self) -> Optional[str]:
        """构建画廊时的问题描述（无问题时为 None）。"""
        return self._build_error

    def city_coordinates(self) -> dict[str, tuple[float, float]]:
        """候选城市坐标表：画廊元数据均值优先，缺失城市用内置城市表。"""
        return dict(self._city_coords)

    def rebuild(self) -> None:
        """重新加载画廊（模型/图片更新后调用）。"""
        self._build()

    # ---- 检索 ----

    def compute_prior(self, image_bytes: bytes) -> Optional[PriorResult]:
        """返回最像的参考城市 + 相似度；画廊为空或模型不可用时返回 None。"""
        if not self._items or not self.descriptor.available:
            return None
        try:
            query = self.descriptor.embed(image_bytes)
        except Exception:  # noqa: BLE001 - 模型/图片异常均静默降级
            return None

        gallery = np.stack([it.vector for it in self._items])  # (N, D)，已归一化
        sims = gallery @ query                                # (N,)

        best_idx = int(np.argmax(sims))
        best = self._items[best_idx]
        score = float(sims[best_idx])

        lat, lon = self._city_coords.get(best.city, (best.lat, best.lon))
        country = best.country or CITY_COORDINATES.get(best.city, ("", "", ""))[2]
        return PriorResult(
            city=best.city,
            country=country,
            lat=lat,
            lon=lon,
            score=score,
            gallery_size=len(self._items),
        )

    # ---- 画廊构建 ----

    def _build(self) -> None:
        self._items = []
        self._city_coords = {}
        self._build_error = None

        metadata = self._load_metadata(self.gallery_dir)
        if metadata is None:
            self._build_error = (
                f"缺少画廊元数据：{self.gallery_dir / 'metadata.json'} 不存在或格式错误"
            )
            return
        if not self.descriptor.available:
            # 懒加载：主动触发一次加载，成功则继续，失败则优雅降级
            try:
                self.descriptor.load()
            except Exception:  # noqa: BLE001
                pass
        if not self.descriptor.available:
            self._build_error = f"MixVPR 模型不可用：{self.descriptor.error or '未知原因'}"
            return

        coords_by_city: dict[str, list[tuple[float, float]]] = {}
        skipped: list[str] = []
        for entry in metadata:
            fname = entry["file"]
            path = self.gallery_dir / fname
            if not path.is_file():
                skipped.append(f"{fname}（文件缺失）")
                continue
            try:
                vec = self.descriptor.embed(path.read_bytes())
            except Exception as e:  # noqa: BLE001 - 单张失败不拖垮画廊
                skipped.append(f"{fname}（embed 失败：{type(e).__name__}）")
                continue
            item = _GalleryItem(
                file=fname,
                city=entry["city"],
                country=entry["country"],
                lat=entry["lat"],
                lon=entry["lon"],
                vector=vec.astype(np.float32),
            )
            self._items.append(item)
            coords_by_city.setdefault(item.city, []).append((item.lat, item.lon))

        # 城市坐标 = 该城市所有图元数据坐标的均值
        for city, coords in coords_by_city.items():
            lats = np.mean([c[0] for c in coords])
            lons = np.mean([c[1] for c in coords])
            self._city_coords[city] = (float(lats), float(lons))
        # 内置城市表兜底
        for city, (lat, lon, _country) in CITY_COORDINATES.items():
            self._city_coords.setdefault(city, (lat, lon))

        if skipped:
            self._build_error = f"{len(skipped)} 张画廊图片被跳过：{skipped[:5]}..."

    @staticmethod
    def _load_metadata(gallery_dir: Path) -> Optional[list[dict]]:
        """读取并清洗 metadata.json，返回 [{file, city, country, lat, lon}]。"""
        meta_path = gallery_dir / "metadata.json"
        if not meta_path.is_file():
            return None
        try:
            raw = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None
        if not isinstance(raw, list):
            return None

        cleaned: list[dict] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            fname = str(entry.get("file", "")).strip()
            city = str(entry.get("city", "")).strip()
            if not fname or not city:
                continue
            cleaned.append({
                "file": fname,
                "city": city,
                "country": str(entry.get("country", "")).strip(),
                "lat": float(entry.get("lat", 0.0) or 0.0),
                "lon": float(entry.get("lon", 0.0) or 0.0),
            })
        return cleaned
