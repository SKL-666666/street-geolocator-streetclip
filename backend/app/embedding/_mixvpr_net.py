"""MixVPR 网络结构 + 权重加载（依赖 torch/torchvision，由 mixvpr.py 延迟导入）。

本模块顶部 import torch / torchvision，仅当真正需要推理时才被加载，
保证 ``app.embedding.mixvpr`` 在未安装 torch 时也能安全 import。
"""
from __future__ import annotations

from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F
import torchvision


# ---------------------------------------------------------------------------
# 网络结构（与官方 https://github.com/amaralibey/MixVPR 一致）
# ---------------------------------------------------------------------------

class FeatureMixerLayer(nn.Module):
    """官方 FeatureMixerLayer：LayerNorm + 双层 MLP + 残差。"""

    def __init__(self, in_dim: int, mlp_ratio: int = 1):
        super().__init__()
        self.in_dim = in_dim
        self.mix = nn.Sequential(
            nn.LayerNorm(in_dim),
            nn.Linear(in_dim, int(in_dim * mlp_ratio)),
            nn.ReLU(),
            nn.Linear(int(in_dim * mlp_ratio), in_dim),
        )
        # 官方初始化（加载权重后会被覆盖，仅保留与官方一致的行为）
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.trunc_normal_(m.weight, std=0.02)
                if m.bias is not None:
                    nn.init.zeros_(m.bias)

    def forward(self, x):
        return x + self.mix(x)


class MixVPR(nn.Module):
    """官方 MixVPR 聚合器：描述子维度 = out_channels × out_rows。"""

    def __init__(self, in_channels: int, in_h: int, in_w: int, out_channels: int,
                 mix_depth: int = 1, mlp_ratio: int = 1, out_rows: int = 4):
        super().__init__()
        self.in_h, self.in_w, self.in_channels = in_h, in_w, in_channels
        self.out_channels, self.out_rows = out_channels, out_rows
        self.mix_depth, self.mlp_ratio = mix_depth, mlp_ratio

        hw = in_h * in_w
        self.mix = nn.Sequential(*[
            FeatureMixerLayer(in_dim=hw, mlp_ratio=mlp_ratio)
            for _ in range(self.mix_depth)
        ])
        self.channel_proj = nn.Linear(in_channels, out_channels)
        self.row_proj = nn.Linear(hw, out_rows)

    def forward(self, x):
        x = x.flatten(2)
        x = self.mix(x)
        x = x.permute(0, 2, 1)
        x = self.channel_proj(x)
        x = x.permute(0, 2, 1)
        x = self.row_proj(x)
        return F.normalize(x.flatten(1), p=2, dim=-1)


class ResNetBackbone(nn.Module):
    """ResNet50 骨干：去掉 avgpool/fc，可按需裁剪 layer4（官方 layers_to_crop=[4]）。"""

    def __init__(self, crop_layer4: bool):
        super().__init__()
        self.model = torchvision.models.resnet50(weights=None)
        self.model.avgpool = None
        self.model.fc = None
        if crop_layer4:
            self.model.layer4 = None
        self.out_channels = 1024 if crop_layer4 else 2048

    def forward(self, x):
        m = self.model
        x = m.conv1(x)
        x = m.bn1(x)
        x = m.relu(x)
        x = m.maxpool(x)
        x = m.layer1(x)
        x = m.layer2(x)
        x = m.layer3(x)
        if m.layer4 is not None:
            x = m.layer4(x)
        return x


class MixVPRModel(nn.Module):
    """backbone + aggregator 组合（state_dict 键名与官方一致：backbone.* / aggregator.*）。"""

    def __init__(self, cfg: "MixVPRConfig"):
        super().__init__()
        self.backbone = ResNetBackbone(crop_layer4=cfg.crop_layer4)
        self.aggregator = MixVPR(
            in_channels=cfg.in_channels,
            in_h=cfg.in_h,
            in_w=cfg.in_w,
            out_channels=cfg.out_channels,
            mix_depth=cfg.mix_depth,
            mlp_ratio=cfg.mlp_ratio,
            out_rows=cfg.out_rows,
        )
        self.cfg = cfg

    def forward(self, x):
        return self.aggregator(self.backbone(x))


# ---------------------------------------------------------------------------
# 架构配置：从 state_dict 自动推断
# ---------------------------------------------------------------------------

class MixVPRConfig:
    """MixVPR 架构配置（可自动推断）。"""

    def __init__(self, crop_layer4: bool, in_channels: int, in_h: int, in_w: int,
                 out_channels: int, out_rows: int, mix_depth: int, mlp_ratio: int):
        self.crop_layer4 = crop_layer4
        self.in_channels = in_channels
        self.in_h = in_h
        self.in_w = in_w
        self.out_channels = out_channels
        self.out_rows = out_rows
        self.mix_depth = mix_depth
        self.mlp_ratio = mlp_ratio

    @property
    def descriptor_dim(self) -> int:
        """输出描述子维度 = out_channels × out_rows。"""
        return self.out_channels * self.out_rows

    def __repr__(self) -> str:  # pragma: no cover - 仅调试用
        return (
            f"MixVPRConfig(crop_layer4={self.crop_layer4}, in={self.in_channels}x"
            f"{self.in_h}x{self.in_w}, out={self.out_channels}x{self.out_rows}, "
            f"mix_depth={self.mix_depth}, mlp_ratio={self.mlp_ratio}, "
            f"descriptor_dim={self.descriptor_dim})"
        )


def detect_config(state_dict: dict) -> MixVPRConfig:
    """从官方 MixVPR state_dict 推断架构参数。"""
    keys = set(state_dict)

    crop_layer4 = not any(k.startswith("backbone.model.layer4.") for k in keys)

    channel_proj_w = state_dict.get("aggregator.channel_proj.weight")
    row_proj_w = state_dict.get("aggregator.row_proj.weight")
    if channel_proj_w is None or row_proj_w is None:
        raise RuntimeError(
            "权重缺少聚合器参数（aggregator.channel_proj.weight / aggregator.row_proj.weight），"
            "不是有效的 MixVPR 检查点"
        )
    out_channels, in_channels = int(channel_proj_w.shape[0]), int(channel_proj_w.shape[1])
    out_rows, hw = int(row_proj_w.shape[0]), int(row_proj_w.shape[1])

    side = int(round(hw ** 0.5))
    if side * side != hw:
        raise RuntimeError(f"特征图 hw={hw} 不是完全平方数，无法推断 in_h/in_w")
    in_h = in_w = side

    # mix 深度：aggregator.mix.{i}.mix.0.weight 的最大索引 + 1
    mix_indices = [
        int(k.split(".")[2])
        for k in keys
        if k.startswith("aggregator.mix.") and k.endswith(".mix.0.weight")
    ]
    mix_depth = (max(mix_indices) + 1) if mix_indices else 1

    # mlp_ratio：第一层 MLP 中间维度 / hw
    mid_w = state_dict.get("aggregator.mix.0.mix.1.weight")
    mlp_ratio = int(mid_w.shape[0]) // hw if mid_w is not None else 1
    mlp_ratio = max(1, mlp_ratio)

    return MixVPRConfig(
        crop_layer4=crop_layer4,
        in_channels=in_channels,
        in_h=in_h,
        in_w=in_w,
        out_channels=out_channels,
        out_rows=out_rows,
        mix_depth=mix_depth,
        mlp_ratio=mlp_ratio,
    )


# ---------------------------------------------------------------------------
# 权重加载
# ---------------------------------------------------------------------------

def load_state_dict(path: Path) -> dict:
    """读取检查点并抽出 MixVPR state_dict（兼容裸 state_dict 与 Lightning 包装）。"""
    for weights_only in (True, False):
        try:
            raw = torch.load(path, map_location="cpu", weights_only=weights_only)
            break
        except Exception:
            if weights_only:
                continue
            raise

    if isinstance(raw, dict):
        # Lightning 检查点通常把权重放在 "state_dict" 键下
        if "aggregator.channel_proj.weight" not in raw and "state_dict" in raw:
            nested = raw["state_dict"]
            if isinstance(nested, dict) and "aggregator.channel_proj.weight" in nested:
                raw = nested
        if "aggregator.channel_proj.weight" not in raw:
            raise RuntimeError(
                f"{path} 不含 MixVPR 权重（缺少 aggregator.channel_proj.weight 键）"
            )
        return raw
    raise RuntimeError(f"{path} 不是包含 state_dict 的 PyTorch 检查点（{type(raw)}）")


def load_mixvpr_model(weights_path: Path) -> tuple[MixVPRModel, MixVPRConfig]:
    """加载 MixVPR 模型。返回 (model, cfg)，model 已 eval()。"""
    state_dict = load_state_dict(weights_path)
    cfg = detect_config(state_dict)
    model = MixVPRModel(cfg)
    missing, unexpected = model.load_state_dict(state_dict, strict=False)
    if missing:
        raise RuntimeError(
            f"权重与架构不匹配，缺少键：{missing[:5]} ...（共 {len(missing)} 个）"
        )
    if unexpected:
        raise RuntimeError(
            f"权重包含架构之外的键：{unexpected[:5]} ...（共 {len(unexpected)} 个）"
        )
    model.eval()
    return model, cfg
