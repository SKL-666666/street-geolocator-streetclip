"""MixVPR 本地 CPU 全局描述子（WACV 2023, https://github.com/amaralibey/MixVPR）。

网络结构与官方仓库一致：ResNet50 骨干（去掉 avgpool/fc，可裁剪 layer4）+ MixVPR
聚合器（FeatureMixer 堆叠 + channel_proj + row_proj），输入图 resize 到 320×320，
输出 L2 归一化描述子。

权重加载策略（自动适配任意 MixVPR 检查点）：
  1. 默认查找 ``<weights_dir>/mixvpr_512.ckpt``（ResNet50 版 512 维官方权重）。
  2. 若默认文件不存在，则扫描权重目录里任意 ``*.ckpt / *.pth / *.pt``，
     并从 state_dict **自动推断** 架构：是否裁剪 layer4、聚合器 channel/row 维度、
     特征图尺寸（in_h×in_w）、mix 深度、输出描述子维度。
     因此官方 4096 维权重（resnet50_MixVPR_4096_channels(1024)_rows(4).ckpt）
     也能直接加载；之后放入 512 维权重会自动切回 512 维输出。

- torch / torchvision / PIL 均延迟导入：本模块 import 时零 torch 依赖，
  未安装 torch 时 embed 给出清晰的 RuntimeError，不影响后端其它功能。
- 线程安全说明：首次 embed 时懒加载模型；之后只读推理，可在多线程下共用实例。
"""
from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Optional

import numpy as np

# backend/models_mixvpr（本文件位于 backend/app/embedding/mixvpr.py）；
# 打包版从 _internal/models_mixvpr 读取（只读资源）
def _default_models_dir() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        base = Path(meipass) if meipass else Path(sys.executable).resolve().parent
        return base / "models_mixvpr"
    return Path(__file__).resolve().parent.parent.parent / "models_mixvpr"


MODELS_DIR = _default_models_dir()
DEFAULT_WEIGHTS_FILE = "mixvpr_512.ckpt"
IMAGE_SIZE = 320  # MixVPR 惯例：输入 resize 到 320×320

# ImageNet 归一化（与官方 demo.py 一致）
_IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

# torch 依赖的网络实现，仅在实际加载/推理时导入
_NET = None


def _net():
    """延迟导入 torch 相关实现（.embedding._mixvpr_net）。"""
    global _NET
    if _NET is None:
        from . import _mixvpr_net

        _NET = _mixvpr_net
    return _NET


class MixVPRDescriptor:
    """MixVPR 全局描述子：懒加载模型与权重（CPU），embed(bytes) -> L2 归一化向量。

    参数:
        weights_dir: 权重目录，默认 ``backend/models_mixvpr``。
        weights_file: 首选权重文件名，默认 ``mixvpr_512.ckpt``；
                      不存在时回退到目录内任意 ``*.ckpt/*.pth/*.pt``。
        image_size: 输入 resize 尺寸（MixVPR 惯例 320）。
        device: 推理设备（默认 cpu）。
    """

    def __init__(self, weights_dir: str | Path | None = None,
                 weights_file: str = DEFAULT_WEIGHTS_FILE,
                 image_size: int = IMAGE_SIZE,
                 device: str = "cpu"):
        self.weights_dir = Path(weights_dir) if weights_dir else MODELS_DIR
        self.weights_file = weights_file
        self.image_size = image_size
        self.device = device
        self._model: Optional[object] = None
        self._cfg: Optional[object] = None
        self._weights_path: Optional[Path] = None
        self._load_error: Optional[str] = None

    # ---- 状态 ----

    @property
    def available(self) -> bool:
        """模型是否已成功加载。"""
        return self._model is not None

    @property
    def descriptor_dim(self) -> Optional[int]:
        """当前加载权重的输出描述子维度（未加载时为 None）。"""
        return self._cfg.descriptor_dim if self._cfg else None

    @property
    def weights_path(self) -> Optional[Path]:
        return self._weights_path

    @property
    def error(self) -> Optional[str]:
        """最近一次加载失败的原因（未失败时为 None）。"""
        return self._load_error

    def reset(self) -> None:
        """释放模型，下次 embed 时重新加载。"""
        self._model = None
        self._cfg = None
        self._weights_path = None
        self._load_error = None

    def load(self) -> None:
        """强制加载模型与权重（懒加载触发器）。失败时抛 RuntimeError 并记录原因。"""
        self._ensure_loaded()

    # ---- 推理 ----

    def embed(self, image_bytes: bytes) -> np.ndarray:
        """对单张图片编码，返回 L2 归一化的 float32 描述子（shape=(descriptor_dim,)）。

        模型不可用 / 权重缺失 / torch 未安装时抛 RuntimeError（信息清晰）。
        """
        self._ensure_loaded()
        try:
            tensor = self._preprocess(image_bytes)
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"输入图片无法解析：{e}") from e

        import torch

        with torch.no_grad():
            vec = self._model(tensor)
        return vec.squeeze(0).cpu().numpy().astype(np.float32)

    # ---- 内部 ----

    def _resolve_weights_path(self) -> Optional[Path]:
        """首选 weights_file，其次扫描目录内任意模型权重文件。"""
        if not self.weights_dir.is_dir():
            return None
        candidate = self.weights_dir / self.weights_file
        if candidate.is_file():
            return candidate
        for pattern in ("*.ckpt", "*.pth", "*.pt"):
            hits = sorted(self.weights_dir.glob(pattern))
            if hits:
                return hits[0]
        return None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        if self._load_error is not None:
            raise RuntimeError(f"MixVPR 模型不可用（此前加载失败）：{self._load_error}")

        try:
            import torch  # noqa: F401
            import torchvision  # noqa: F401
            net = _net()
        except ImportError as e:  # pragma: no cover - 环境相关
            self._load_error = (
                f"未安装 torch/torchvision（{e}）。请先执行："
                "pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu"
            )
            raise RuntimeError(f"MixVPR 模型不可用：{self._load_error}") from e

        path = self._resolve_weights_path()
        if path is None:
            self._load_error = (
                f"未找到 MixVPR 权重：目录 {self.weights_dir} 下既没有 {self.weights_file}，"
                "也没有其它 *.ckpt / *.pth / *.pt 权重文件。"
            )
            raise RuntimeError(f"MixVPR 模型不可用：{self._load_error}")

        try:
            model, cfg = net.load_mixvpr_model(path)
            model.to(self.device).eval()
        except Exception as e:  # noqa: BLE001
            self._load_error = f"加载权重 {path} 失败：{type(e).__name__}: {e}"
            raise RuntimeError(f"MixVPR 模型不可用：{self._load_error}") from e

        self._model = model
        self._cfg = cfg
        self._weights_path = path

    def _preprocess(self, image_bytes: bytes):
        """与官方 demo.py 一致：RGB → resize(320,320) BICUBIC → ToTensor → ImageNet 归一化。"""
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes))
        img = img.convert("RGB")
        img = img.resize((self.image_size, self.image_size), Image.BICUBIC)

        arr = np.asarray(img, dtype=np.float32) / 255.0
        arr = (arr - _IMAGENET_MEAN) / _IMAGENET_STD
        import torch

        tensor = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0)
        return tensor


def build_descriptor(weights_dir: str | Path | None = None, **kwargs) -> MixVPRDescriptor:
    """便捷工厂：创建 MixVPRDescriptor。"""
    return MixVPRDescriptor(weights_dir=weights_dir, **kwargs)
