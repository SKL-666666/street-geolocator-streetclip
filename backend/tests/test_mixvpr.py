"""MixVPR 描述子 + 地理先验引擎单元测试。

关键约定：
- 权重缺失 / 模型不可用 时，PriorEngine 必须优雅降级（available=False，
  compute_prior 返回 None），不抛异常、不拖垮调用方。
- 模型可用时，embed 输出 L2 归一化向量，维度与加载权重的描述子维度一致
  （512 维权重 → 512；当前镜像仅有官方 4096 维权重时 → 4096，测试自动适配）。
"""
from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from app.embedding.mixvpr import MixVPRDescriptor
from app.pipeline.prior import PriorEngine, PriorResult

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"
REAL_BUDAPEST = DATA_DIR / "real_budapest.jpg"
REAL_KYIV = DATA_DIR / "real_kyiv.jpg"


def _jpeg_bytes(size: tuple[int, int] = (64, 48), color: tuple[int, int, int] = (90, 140, 200)) -> bytes:
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _model_available() -> bool:
    """真实模型权重是否就位（backend/models_mixvpr 下有 .ckpt/.pth/.pt）。"""
    from app.embedding.mixvpr import MODELS_DIR

    if not MODELS_DIR.is_dir():
        return False
    return any(MODELS_DIR.glob("*.ckpt")) or any(MODELS_DIR.glob("*.pth")) or any(MODELS_DIR.glob("*.pt"))


needs_model = pytest.mark.skipif(not _model_available(), reason="未放置 MixVPR 权重，跳过需要模型的测试")


# ---------------------------------------------------------------------------
# 模型不可用路径（权重缺失 → 优雅降级）
# ---------------------------------------------------------------------------

class TestModelUnavailable:
    def test_descriptor_embed_raises_without_weights(self, tmp_path: Path):
        """权重目录为空时，embed 抛 RuntimeError 且错误信息清晰。"""
        desc = MixVPRDescriptor(weights_dir=tmp_path)
        with pytest.raises(RuntimeError, match="未找到 MixVPR 权重"):
            desc.embed(_jpeg_bytes())
        assert desc.available is False
        assert desc.descriptor_dim is None
        assert "未找到" in (desc.error or "")

    def test_prior_engine_empty_gallery_returns_none(self, tmp_path: Path):
        """画廊目录没有任何内容时，compute_prior 返回 None，不崩溃。"""
        engine = PriorEngine(gallery_dir=tmp_path)
        assert engine.available is False
        assert engine.gallery_size == 0
        assert engine.compute_prior(_jpeg_bytes()) is None

    def test_prior_engine_missing_metadata_returns_none(self, tmp_path: Path):
        """画廊有图但缺 metadata.json 时，返回 None。"""
        (tmp_path / "budapest_1.jpg").write_bytes(_jpeg_bytes())
        engine = PriorEngine(gallery_dir=tmp_path)
        assert engine.available is False
        assert engine.compute_prior(_jpeg_bytes()) is None

    def test_prior_engine_garbage_metadata_returns_none(self, tmp_path: Path):
        """metadata.json 格式损坏时，返回 None。"""
        (tmp_path / "budapest_1.jpg").write_bytes(_jpeg_bytes())
        (tmp_path / "metadata.json").write_text("not json [[[", encoding="utf-8")
        engine = PriorEngine(gallery_dir=tmp_path)
        assert engine.available is False
        assert engine.compute_prior(_jpeg_bytes()) is None

    def test_prior_engine_model_unavailable_returns_none(self, tmp_path: Path):
        """元数据齐全但模型权重缺失时，返回 None（关键降级路径）。"""
        gallery = tmp_path / "gallery"
        gallery.mkdir()
        (gallery / "budapest_1.jpg").write_bytes(_jpeg_bytes())
        (gallery / "metadata.json").write_text(
            json.dumps([{"file": "budapest_1.jpg", "city": "Budapest",
                         "country": "Hungary", "lat": 47.4979, "lon": 19.0402}]),
            encoding="utf-8",
        )
        engine = PriorEngine(gallery_dir=gallery, descriptor=MixVPRDescriptor(weights_dir=tmp_path / "empty_weights"))
        assert engine.available is False
        assert engine.build_error and "模型不可用" in engine.build_error
        assert engine.compute_prior(_jpeg_bytes()) is None


# ---------------------------------------------------------------------------
# 模型可用路径（需真实权重）
# ---------------------------------------------------------------------------

@needs_model
class TestWithModel:
    def test_embed_dim_and_l2_norm(self):
        """embed 输出维度与描述子维度一致，且 L2 归一化。"""
        desc = MixVPRDescriptor()
        vec = desc.embed(_jpeg_bytes(size=(320, 320)))
        assert isinstance(vec, np.ndarray)
        assert vec.shape == (desc.descriptor_dim,)
        assert vec.dtype == np.float32
        assert abs(float(np.linalg.norm(vec)) - 1.0) < 1e-4
        # 512 维权重 → 512；4096 维权重 → 4096（测试自动适配）
        assert desc.descriptor_dim in (512, 4096, 128)

    def test_embed_reproducible(self):
        desc = MixVPRDescriptor()
        data = _jpeg_bytes(size=(320, 320))
        v1 = desc.embed(data)
        v2 = desc.embed(data)
        assert np.allclose(v1, v2, atol=1e-6)

    def test_prior_engine_retrieval_top1(self, tmp_path: Path):
        """小型画廊检索：查询 real_budapest.jpg → 应命中 Budapest。"""
        gallery = tmp_path / "gallery"
        gallery.mkdir()
        gallery.joinpath("budapest_1.jpg").write_bytes(REAL_BUDAPEST.read_bytes())
        gallery.joinpath("kyiv_1.jpg").write_bytes(REAL_KYIV.read_bytes())
        gallery.joinpath("metadata.json").write_text(
            json.dumps([
                {"file": "budapest_1.jpg", "city": "Budapest", "country": "Hungary",
                 "lat": 47.4979, "lon": 19.0402},
                {"file": "kyiv_1.jpg", "city": "Kyiv", "country": "Ukraine",
                 "lat": 50.4501, "lon": 30.5234},
            ]),
            encoding="utf-8",
        )
        engine = PriorEngine(gallery_dir=gallery)
        assert engine.available
        assert engine.gallery_size == 2

        result = engine.compute_prior(REAL_BUDAPEST.read_bytes())
        assert isinstance(result, PriorResult)
        assert result.city == "Budapest"
        assert result.country == "Hungary"
        assert result.gallery_size == 2
        assert 0.0 <= result.score <= 1.0

        coords = engine.city_coordinates()
        assert "Budapest" in coords and "Kyiv" in coords

    def test_prior_engine_query_unrelated_returns_something(self, tmp_path: Path):
        """对任意图调用 compute_prior 都应返回一个结果（模型可用时）。"""
        gallery = tmp_path / "gallery"
        gallery.mkdir()
        gallery.joinpath("b.jpg").write_bytes(REAL_BUDAPEST.read_bytes())
        gallery.joinpath("metadata.json").write_text(
            json.dumps([{"file": "b.jpg", "city": "Budapest",
                         "country": "Hungary", "lat": 47.4979, "lon": 19.0402}]),
            encoding="utf-8",
        )
        engine = PriorEngine(gallery_dir=gallery)
        result = engine.compute_prior(_jpeg_bytes(size=(320, 320)))
        assert result is not None
        assert result.city == "Budapest"
        assert result.gallery_size == 1
