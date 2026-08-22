"""MixVPR 先验的单例管理：模型与画廊只加载一次，供管线复用。"""
from __future__ import annotations

import threading
from typing import Optional

from ..config import settings
from .prior import PriorEngine, PriorResult

_lock = threading.Lock()
_engine: Optional[PriorEngine] = None


def get_prior_engine() -> Optional[PriorEngine]:
    """懒加载单例；画廊/模型不可用时返回 None（调用方静默降级）。"""
    global _engine
    if not settings.enable_prior:
        return None
    with _lock:
        if _engine is None:
            try:
                _engine = PriorEngine()
            except Exception:
                _engine = None
        return _engine


def compute_prior(image_bytes: bytes, min_score: float | None = None) -> Optional[PriorResult]:
    """对查询图计算城市级先验；不可用或低于阈值返回 None。

    min_score=None 时用 settings.prior_min_score；传入 -1.0 表示不设下限
    （降级路径用来取"任意相似度的最佳匹配"，保证有候选可展示）。
    """
    engine = get_prior_engine()
    if engine is None or not engine.available:
        return None
    try:
        prior = engine.compute_prior(image_bytes)
    except Exception:
        return None
    if prior is None:
        return None
    threshold = settings.prior_min_score if min_score is None else min_score
    if prior.score < threshold:
        return None
    return prior
