"""B1：街景索引检索（numpy 向量库，此规模与 FAISS 等价，零额外依赖）。

索引构建：scripts/build_index.py → data/index/{city}.faiss.npy + {city}.json
检索：StreetIndex.search(image_bytes, k) → 候选坐标（街道级）
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional

import numpy as np

from ..config import settings
from ..embedding.mixvpr import MixVPRDescriptor

INDEX_DIR = settings.data_dir / "index"
_lock = threading.Lock()
_registry: dict[str, "StreetIndex"] = {}
_descriptor: Optional[MixVPRDescriptor] = None


def _get_descriptor() -> Optional[MixVPRDescriptor]:
    """共享描述子实例（懒加载，触发 load）。"""
    global _descriptor
    if _descriptor is None:
        _descriptor = MixVPRDescriptor()
    if not _descriptor.available:
        try:
            _descriptor.load()
        except Exception:
            pass
    return _descriptor if _descriptor.available else None


class StreetIndex:
    """单城街景索引：向量矩阵 + 元数据。"""

    def __init__(self, city: str, vectors: np.ndarray, meta: list[dict]):
        self.city = city
        self.vectors = vectors.astype(np.float32)  # (N, D) L2 归一化
        self.meta = meta

    @classmethod
    def load(cls, city: str, index_dir: Path | None = None) -> Optional["StreetIndex"]:
        d = index_dir or INDEX_DIR
        vec_path = d / f"{city}.faiss.npy"
        meta_path = d / f"{city}.json"
        if not vec_path.exists() or not meta_path.exists():
            return None
        vectors = np.load(vec_path)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return cls(city, vectors, meta)

    def search(self, descriptor: np.ndarray, k: int = 5) -> list[dict]:
        """最近邻检索（内积 = 余弦，向量已归一化）。"""
        if self.vectors.shape[0] == 0:
            return []
        sims = self.vectors @ descriptor.reshape(-1)
        idx = np.argsort(-sims)[:k]
        out = []
        for i in idx:
            m = self.meta[int(i)]
            out.append({"lat": m["lat"], "lon": m["lon"],
                        "score": float(sims[int(i)]),
                        "captured_at": m.get("captured_at", "")})
        return out


def get_index(city: str) -> Optional[StreetIndex]:
    """按城市名取索引（进程内缓存，懒加载）。"""
    with _lock:
        if city in _registry:
            return _registry[city]
        idx = StreetIndex.load(city)
        if idx is not None:
            _registry[city] = idx
        return idx


def search_city(city: str, image_bytes: bytes, k: int = 5,
                descriptor: Optional[MixVPRDescriptor] = None) -> list[dict]:
    """对单城索引检索；索引缺失/模型不可用返回空列表。"""
    idx = get_index(city)
    if idx is None:
        return []
    desc = descriptor or _get_descriptor()
    if desc is None:
        return []
    try:
        vec = desc.embed(image_bytes)
    except Exception:
        return []
    return idx.search(vec, k=k)


def list_indexes() -> list[str]:
    """已建索引的城市清单。"""
    if not INDEX_DIR.exists():
        return []
    return sorted(p.stem for p in INDEX_DIR.glob("*.json") if p.stem != "manifest")
